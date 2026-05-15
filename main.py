#!/usr/bin/env python3
"""12306 铁路数据爬虫入口

按顺序执行:
  Phase 1: 站点采集
  Phase 2: 车次发现
  Phase 3: 时刻表采集

 用法:
  python main.py                # 完整执行 (自动断点续传)
  python main.py --phase 2      # 仅执行车次发现
  python main.py --fresh        # 忽略历史进度, 从头开始

依赖: pip install -r requirements.txt
"""

import argparse
import asyncio
import os
import time

from config import PROGRESS_DISCOVER, PROGRESS_SCHEDULES
from crawler.db import init_db
from crawler.stations import fetch_all_stations, classify_stations
from crawler.discover import discover_trains
from crawler.schedules import fetch_all_schedules
from crawler.export import export_all


async def phase1() -> tuple[list[dict], list[dict]]:
    """Phase 1: 采集并分类站点."""
    print("=" * 60)
    print("Phase 1: 站点数据采集")
    print("=" * 60)

    all_stations = await fetch_all_stations()
    print(f"  全部站点: {len(all_stations)} 个")

    hubs, spokes = classify_stations(all_stations)
    print(f"  枢纽站: {len(hubs)} 个")
    print(f"  辐射站: {len(spokes)} 个 (地级市)")
    print(f"  辐射站预览: {', '.join(s['name'] for s in spokes[:10])} ...")
    print()

    return hubs, spokes


async def phase2(hubs: list[dict], spokes: list[dict]):
    """Phase 2: 车次发现."""
    print("=" * 60)
    print("Phase 2: 车次发现")
    print("=" * 60)

    t0 = time.time()
    discovered = await discover_trains(hubs, spokes)
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f} 秒")
    print()

    return discovered


async def phase3(discovered: dict):
    """Phase 3: 时刻表采集."""
    print("=" * 60)
    print("Phase 3: 时刻表采集")
    print("=" * 60)

    if not discovered:
        print("  无车次需要采集, 跳过")
        return

    t0 = time.time()
    count = await fetch_all_schedules(discovered)
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f} 秒")
    print()

    return count


async def main():
    parser = argparse.ArgumentParser(description="12306 铁路数据爬虫")
    parser.add_argument(
        "--phase",
        type=int,
        choices=[1, 2, 3],
        help="仅执行指定阶段 (1=站点, 2=车次发现, 3=时刻表)",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="忽略上次进度, 从头开始爬取",
    )
    args = parser.parse_args()

    if args.fresh:
        for f in [PROGRESS_DISCOVER, PROGRESS_SCHEDULES]:
            if os.path.exists(f):
                os.remove(f)
                print(f"  [fresh] 已删除 {f}")

    init_db()

    show_phase = args.phase
    total_start = time.time()

    hubs, spokes = [], []
    discovered = {}

    # Phase 1
    if show_phase is None or show_phase == 1:
        hubs, spokes = await phase1()
    else:
        all_stations = await fetch_all_stations()
        hubs, spokes = classify_stations(all_stations)

    # Phase 2
    if show_phase is None or show_phase == 2:
        discovered = await phase2(hubs, spokes)
    else:
        from crawler.db import get_conn
        conn = get_conn()
        rows = conn.execute(
            "SELECT train_no, train_number, train_type, from_telecode, to_telecode, "
            "from_station, to_station, depart_time, arrive_time, duration FROM trains"
        ).fetchall()
        conn.close()
        discovered = {
            r[0]: {
                "train_no": r[0],
                "train_number": r[1],
                "train_type": r[2],
                "from_telecode": r[3],
                "to_telecode": r[4],
                "from_station": r[5],
                "to_station": r[6],
                "depart_time": r[7],
                "arrive_time": r[8],
                "duration": r[9],
            }
            for r in rows
        }

    # Phase 3
    if show_phase is None or show_phase == 3:
        await phase3(discovered)

    # 全量导出 JSON
    export_all(hubs, spokes)

    total_elapsed = time.time() - total_start
    print("=" * 60)
    print(f"全部完成! 总耗时: {total_elapsed:.1f} 秒 ({total_elapsed/60:.1f} 分钟)")
    print(f"数据库: data/railway.db")


if __name__ == "__main__":
    asyncio.run(main())
