"""Phase 3: 车次时刻表采集

为每条已发现的车次查询完整停站序列。
"""

import asyncio
import json
import os

from config import (
    TRAIN_SCHEDULE_URL,
    MAX_CONCURRENT,
    REQUEST_INTERVAL,
    BACKOFF_BASE,
    MAX_RETRIES,
    PROGRESS_SCHEDULES,
    query_date,
)
from crawler.session import build_headers, create_session
from crawler.db import get_conn


def _parse_stopover(stopover_text: str) -> str:
    """将停留时间文本转为分钟数."""
    if not stopover_text or stopover_text == "----":
        return ""
    stopover_text = stopover_text.replace("分钟", "").replace("分", "").strip()
    try:
        int(stopover_text)
        return stopover_text
    except ValueError:
        return stopover_text


def _to_minutes(time_str: str) -> int | None:
    """时间字符串转分钟数 (用于排序/比较), 不支持跨日."""
    if not time_str or time_str == "----":
        return None
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    return None


async def fetch_all_schedules(
    discovered: dict[str, dict],
) -> int:
    """为所有发现的车次查询完整时刻表. 返回成功查询的条数."""
    train_infos = list(discovered.values())
    train_date = query_date()

    # 断点续传
    start_idx = 0
    if os.path.exists(PROGRESS_SCHEDULES):
        try:
            with open(PROGRESS_SCHEDULES, "r", encoding="utf-8") as f:
                saved = json.load(f)
            start_idx = saved.get("next_idx", 0)
            print(f"  [恢复] 从第 {start_idx}/{len(train_infos)} 车次继续")
        except Exception:
            start_idx = 0

    # 预加载 telecode 映射表
    conn = get_conn()
    rows = conn.execute("SELECT name, telecode FROM stations").fetchall()
    name_to_telecode = {row[0]: row[1] for row in rows}
    conn.close()

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    progress_lock = asyncio.Lock()
    db_lock = asyncio.Lock()

    # 统计
    stats = {"success": 0, "fail": 0, "total": len(train_infos)}

    client = await create_session()
    try:

        async def query_schedule(idx: int):
            nonlocal stats

            if idx < start_idx:
                return

            info = train_infos[idx]
            train_no = info["train_no"]
            from_tc = info.get("from_telecode", info.get("query_from", ""))
            to_tc = info.get("to_telecode", info.get("query_to", ""))

            async with sem:
                await asyncio.sleep(REQUEST_INTERVAL)

                for attempt in range(MAX_RETRIES):
                    try:
                        resp = await client.get(
                            TRAIN_SCHEDULE_URL,
                            params={
                                "train_no": train_no,
                                "from_station_telecode": from_tc,
                                "to_station_telecode": to_tc,
                                "depart_date": train_date,
                            },
                        )
                        break
                    except Exception:
                        if attempt == MAX_RETRIES - 1:
                            async with progress_lock:
                                stats["fail"] += 1
                            return
                        await asyncio.sleep(BACKOFF_BASE * (2**attempt))

                if resp.status_code != 200:
                    async with progress_lock:
                        stats["fail"] += 1
                    return

                content_type = resp.headers.get("content-type", "")
                text = resp.text.strip()
                if "json" not in content_type and not text.startswith("{"):
                    async with progress_lock:
                        stats["fail"] += 1
                    return

                try:
                    data = resp.json()
                except Exception:
                    async with progress_lock:
                        stats["fail"] += 1
                    return

                if not data.get("status"):
                    async with progress_lock:
                        stats["fail"] += 1
                    return

                schedule_data = data.get("data", {})
                stops = schedule_data.get("data", [])

                if not stops or not isinstance(stops, list):
                    async with progress_lock:
                        stats["fail"] += 1
                    return

                # 解析停站序列
                stop_records = []
                running_day = 0
                prev_depart_minutes: int | None = None
                for stop in stops:
                    seq = stop.get("station_no", "0")
                    try:
                        seq = int(seq)
                    except (ValueError, TypeError):
                        seq = 0
                    station_name = stop.get("station_name", "")
                    arrive_time = stop.get("arrive_time", "")
                    depart_time = stop.get("start_time", "")
                    stop_minutes = _parse_stopover(stop.get("stopover_time", ""))
                    distance = stop.get("distance", "0")

                    # 映射 telecode
                    telecode = name_to_telecode.get(station_name, "")

                    # 日期间隔: 比较本站到达时间与上一站发车时间
                    arr_m = _to_minutes(arrive_time)
                    dep_m = _to_minutes(depart_time)
                    if arr_m is not None and prev_depart_minutes is not None:
                        if arr_m < prev_depart_minutes:
                            running_day += 1
                    day_offset = running_day
                    if dep_m is not None:
                        prev_depart_minutes = dep_m

                    stop_records.append(
                        (
                            train_no,
                            seq,
                            station_name,
                            telecode,
                            arrive_time,
                            depart_time,
                            stop_minutes,
                            distance,
                            day_offset,
                        )
                    )

                # 批量写入 (加锁防止并发写入冲突)
                if stop_records:
                    async with db_lock:
                        db_conn = get_conn()
                        db_conn.execute(
                            "DELETE FROM train_stops WHERE train_no = ?", (train_no,)
                        )
                        db_conn.executemany(
                            """INSERT OR REPLACE INTO train_stops
                               (train_no, seq, station_name, station_telecode,
                                arrive_time, depart_time, stop_minutes, distance_km, day_offset)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            stop_records,
                        )
                        db_conn.commit()
                        db_conn.close()

                async with progress_lock:
                    stats["success"] += 1

        # 批量执行
        batch_size = MAX_CONCURRENT * 5
        for batch_start in range(start_idx, len(train_infos), batch_size):
            batch_end = min(batch_start + batch_size, len(train_infos))
            tasks = [query_schedule(i) for i in range(batch_start, batch_end)]
            await asyncio.gather(*tasks)

            # 保存进度
            async with progress_lock:
                with open(PROGRESS_SCHEDULES, "w", encoding="utf-8") as f:
                    json.dump({"next_idx": batch_end}, f, ensure_ascii=False)

            print(
                f"  [时刻表] {batch_end}/{stats['total']} 完成, "
                f"成功 {stats['success']}, 失败 {stats['fail']}"
            )

    finally:
        await client.aclose()

    print(
        f"  [完成] 共处理 {stats['success']} 车次时刻表, "
        f"失败 {stats['fail']} 条"
    )
    return stats["success"]
