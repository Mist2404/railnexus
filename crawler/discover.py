"""Phase 2: 车次发现

通过 12306 leftTicket 接口，在枢纽站与辐射站之间交叉查询，
收集去重后的全部车次。
"""

import asyncio
import json
import os
import re
from urllib.parse import unquote

import httpx

from config import (
    LEFT_TICKET_URL,
    INIT_URL,
    MAX_CONCURRENT,
    REQUEST_INTERVAL,
    BACKOFF_BASE,
    MAX_RETRIES,
    STOP_AFTER_NO_NEW,
    PROGRESS_DISCOVER,
    query_date,
)
from crawler.session import build_headers, create_session
from crawler.db import get_conn


def _parse_result(result_str: str) -> dict | None:
    """解析 leftTicket 返回的单条结果.

    结果格式 (管道分隔):
    secretStr|预订|train_no|station_train_code|start_station_telecode|
    end_station_telecode|from_station_telecode|to_station_telecode|
    start_time|arrive_time|lishi|...

    返回: {train_no, train_number, train_type, from_telecode, to_telecode,
           from_station, to_station, depart_time, arrive_time, duration}
    """
    parts = result_str.split("|")
    if len(parts) < 8:
        return None

    # 查找 train_no (找到"预订"后取下一字段, 或匹配 \d+[A-Z]\d+ 模式)
    idx = -1
    for i, p in enumerate(parts):
        if p == "预订" and i + 1 < len(parts):
            idx = i + 1
            break
    if idx < 0:
        # 回退: 匹配 train_no 特征 (至少 8 位, 含数字+字母)
        for i, p in enumerate(parts):
            if len(p) >= 8 and re.match(r"^\d+[A-Z]\d+$", p):
                idx = i
                break
    if idx < 0 or idx + 1 >= len(parts):
        return None

    train_no = parts[idx]
    next_part = parts[idx + 1]
    if not next_part or not re.match(r"^[A-Z]\d+", next_part):
        return None
    train_number = next_part
    train_type = train_number[0]

    def _get(offset: int, default: str = "") -> str:
        i = idx + offset
        return parts[i] if i < len(parts) and parts[i] else default

    from_telecode = _get(2)
    to_telecode = _get(3)
    q_from = _get(4)
    q_to = _get(5)
    depart_time = _get(6)
    arrive_time = _get(7)
    duration = _get(8)

    return {
        "train_no": train_no,
        "train_number": train_number,
        "train_type": train_type,
        "from_telecode": from_telecode,
        "to_telecode": to_telecode,
        "query_from": q_from,
        "query_to": q_to,
        "depart_time": depart_time,
        "arrive_time": arrive_time,
        "duration": duration,
    }


def _build_query_pairs(
    hubs: list[dict], spokes: list[dict]
) -> list[tuple[str, str, str, str]]:
    """构建查询对列表.

    返回: [(from_telecode, to_telecode, from_name, to_name), ...]
    """
    hub_items = [(h["telecode"], h["name"]) for h in hubs]
    spoke_items = [(s["telecode"], s["name"]) for s in spokes]

    # 去重: 同一 telegram code 不出现在 spokes 里
    hub_tc_set = {tc for tc, _ in hub_items}
    spoke_items = [(tc, name) for tc, name in spoke_items if tc not in hub_tc_set]

    pairs_set: set[tuple[str, str, str, str]] = set()

    # 枢纽 ↔ 枢纽 (全部双向)
    for tc1, n1 in hub_items:
        for tc2, n2 in hub_items:
            if tc1 != tc2:
                pairs_set.add((tc1, tc2, n1, n2))

    # 枢纽 ↔ 辐射 (双向)
    for h_tc, h_name in hub_items:
        for s_tc, s_name in spoke_items:
            pairs_set.add((h_tc, s_tc, h_name, s_name))
            pairs_set.add((s_tc, h_tc, s_name, h_name))

    return list(pairs_set)


async def discover_trains(
    hub_stations: list[dict],
    spoke_stations: list[dict],
) -> dict[str, dict]:
    """执行车次发现, 返回 {train_no: train_info, ...} 字典."""
    pairs = _build_query_pairs(hub_stations, spoke_stations)
    train_date = query_date()

    # 断点续传
    start_idx = 0
    discovered: dict[str, dict] = {}
    if os.path.exists(PROGRESS_DISCOVER):
        try:
            with open(PROGRESS_DISCOVER, "r", encoding="utf-8") as f:
                saved = json.load(f)
            start_idx = saved.get("next_idx", 0)
            discovered = saved.get("discovered", {})
            print(f"  [恢复] 从第 {start_idx}/{len(pairs)} 对继续, 已发现 {len(discovered)} 车次")
        except Exception:
            start_idx = 0
            discovered = {}

    # 准备数据库
    conn = get_conn()

    no_new_count = 0
    total_discovered = len(discovered)

    sem = asyncio.Semaphore(MAX_CONCURRENT)
    progress_lock = asyncio.Lock()
    train_lock = asyncio.Lock()

    processed = [0]

    # 创建共享客户端 (先获取 session cookie, 再复用连接)
    client = await create_session()
    try:

        async def query_one(idx: int) -> int:
            """查询一对站点, 返回: -1=异常, 0=无结果, 1=有结果但无新车次, 2=发现新车次."""
            nonlocal total_discovered

            if idx < start_idx:
                return -1

            from_tc, to_tc, from_name, to_name = pairs[idx]

            async with sem:
                await asyncio.sleep(REQUEST_INTERVAL)

                for attempt in range(MAX_RETRIES):
                    try:
                        resp = await client.get(
                            LEFT_TICKET_URL,
                            params={
                                "leftTicketDTO.train_date": train_date,
                                "leftTicketDTO.from_station": from_tc,
                                "leftTicketDTO.to_station": to_tc,
                                "purpose_codes": "ADULT",
                            },
                        )
                        break
                    except Exception as e:
                        if attempt == MAX_RETRIES - 1:
                            return -1
                        wait = BACKOFF_BASE * (2**attempt)
                        await asyncio.sleep(wait)

                if resp.status_code in (429, 403):
                    await asyncio.sleep(BACKOFF_BASE * 3)
                    return -1

                if resp.status_code != 200:
                    return -1

                # 检查是否为 JSON (防止被重定向到验证码页)
                content_type = resp.headers.get("content-type", "")
                if "json" not in content_type and not resp.text.strip().startswith("{"):
                    return -1

                try:
                    data = resp.json()
                except Exception:
                    return -1

                if not data.get("status"):
                    return -1

                result_data = data.get("data", {})
                results = result_data.get("result", [])
                station_map = result_data.get("map", {})

                if not results:
                    return 0  # 无直达车

                found_new = False
                for r in results:
                    # queryG 返回的结果是多行 URL 编码, 最后一行是管道分隔的列车数据
                    decoded = unquote(r)
                    pipe_line = ""
                    for line in decoded.splitlines():
                        line = line.strip()
                        if "|预订|" in line or "|" in line:
                            pipe_line = line
                    if not pipe_line:
                        continue
                    info = _parse_result(pipe_line)
                    if not info or not info["train_no"]:
                        continue

                    # 补全站名
                    info["from_station"] = station_map.get(
                        info["from_telecode"], info["from_telecode"]
                    )
                    info["to_station"] = station_map.get(
                        info["to_telecode"], info["to_telecode"]
                    )

                    async with train_lock:
                        if info["train_no"] not in discovered:
                            discovered[info["train_no"]] = info
                            _save_train(conn, info)
                            total_discovered = len(discovered)
                            found_new = True

                return 2 if found_new else 1

        # 批量并发执行
        batch_size = MAX_CONCURRENT * 10
        for batch_start in range(start_idx, len(pairs), batch_size):
            batch_end = min(batch_start + batch_size, len(pairs))
            tasks = [query_one(i) for i in range(batch_start, batch_end)]
            results = await asyncio.gather(*tasks)

            # 更新"无结果"计数器 (仅空结果触发, 有结果但无新车次不触发)
            for ret in results:
                if ret == 2:
                    no_new_count = 0
                elif ret == 0:
                    no_new_count += 1
                # ret == 1 或 -1: 不改变计数器

            processed[0] = batch_end

            # 每批保存进度
            async with progress_lock:
                with open(PROGRESS_DISCOVER, "w", encoding="utf-8") as f:
                    json.dump(
                        {"next_idx": batch_end, "discovered": discovered},
                        f,
                        ensure_ascii=False,
                    )

            print(
                f"  [发现] {processed[0]}/{len(pairs)} 对查询完成, "
                f"累计 {total_discovered} 车次, "
                f"连续空 {no_new_count}/{STOP_AFTER_NO_NEW}"
            )

            # 连续 N 次无新车次, 提前终止
            if no_new_count >= STOP_AFTER_NO_NEW:
                print(f"  [终止] 连续 {STOP_AFTER_NO_NEW} 次无新车次, 提前结束")
                break

    finally:
        conn.close()
        await client.aclose()

    print(f"  [完成] 共发现 {total_discovered} 条唯一车次")
    return discovered


def _save_train(conn, info: dict):
    """保存单条车次到数据库."""
    conn.execute(
        """INSERT OR IGNORE INTO trains
           (train_no, train_number, train_type, from_telecode, to_telecode,
            from_station, to_station, depart_time, arrive_time, duration)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            info["train_no"],
            info["train_number"],
            info["train_type"],
            info.get("from_telecode", ""),
            info.get("to_telecode", ""),
            info.get("from_station", ""),
            info.get("to_station", ""),
            info.get("depart_time", ""),
            info.get("arrive_time", ""),
            info.get("duration", ""),
        ),
    )
    conn.commit()
