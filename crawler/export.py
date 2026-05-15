"""从 railway.db 导出整理好的 JSON 文件."""

import json
import sqlite3
import os

from config import DB_PATH

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _conn():
    return sqlite3.connect(DB_PATH)


def export_stations():
    """导出站点相关的 JSON 文件."""
    conn = _conn()

    # 读取全部站点
    rows = conn.execute(
        "SELECT name, telecode, pinyin, city FROM stations"
    ).fetchall()

    # 1. stations_by_tc.json — 电报码索引
    by_tc = {}
    for r in rows:
        by_tc[r[1]] = {"name": r[0], "pinyin": r[2], "city": r[3]}

    _write("stations_by_tc.json", by_tc)
    print(f"  stations_by_tc.json — {len(by_tc)} 条")

    # 2. stations_by_city.json — 按城市分组
    by_city = {}
    for tc, info in by_tc.items():
        city = info["city"] or "未知"
        by_city.setdefault(city, []).append({"tc": tc, **info})

    _write("stations_by_city.json", by_city)
    print(f"  stations_by_city.json — {len(by_city)} 个城市")

    # 3. stations_map.json — 站名 → 电报码
    name_map = {}
    for tc, info in by_tc.items():
        name_map[info["name"]] = tc

    _write("stations_map.json", name_map)
    print(f"  stations_map.json — {len(name_map)} 条")

    conn.close()


def export_hubs_and_spokes(hubs: list[dict], spokes: list[dict]):
    """导出枢纽站和辐射站清单."""
    _write(
        "hubs.json",
        [{"name": s["name"], "tc": s["telecode"], "city": s.get("city", "")} for s in hubs],
    )
    print(f"  hubs.json — {len(hubs)} 个枢纽站")

    _write(
        "spokes.json",
        [{"name": s["name"], "tc": s["telecode"], "city": s.get("city", "")} for s in spokes],
    )
    print(f"  spokes.json — {len(spokes)} 个辐射站")


def export_trains():
    """导出车次列表."""
    conn = _conn()
    rows = conn.execute(
        "SELECT train_no, train_number, train_type, from_telecode, to_telecode, "
        "from_station, to_station, depart_time, arrive_time, duration FROM trains"
    ).fetchall()

    if not rows:
        print("  (无车次数据, 跳过)")
        conn.close()
        return

    trains = [
        {
            "train_no": r[0],
            "train_number": r[1],
            "train_type": r[2],
            "from_tc": r[3],
            "to_tc": r[4],
            "from_station": r[5],
            "to_station": r[6],
            "depart": r[7],
            "arrive": r[8],
            "duration": r[9],
        }
        for r in rows
    ]
    _write("trains.json", trains)
    print(f"  trains.json — {len(trains)} 条车次")
    conn.close()


def export_adjacency():
    """导出邻接表: {from_tc: [{to_tc, train_no, depart, arrive}, ...]}"""
    conn = _conn()
    rows = conn.execute(
        "SELECT train_no, station_telecode, depart_time "
        "FROM train_stops WHERE depart_time != '----' ORDER BY train_no, seq"
    ).fetchall()

    if not rows:
        print("  (无停站数据, 跳过)")
        conn.close()
        return

    # 按车次分组, 保持停站顺序
    train_stops: dict[str, list[tuple[str, str]]] = {}
    for train_no, tc, depart in rows:
        train_stops.setdefault(train_no, []).append((tc, depart))

    # 构建邻接: 对每个车次, 将每个停站与其后续所有停站连接
    adjacency: dict[str, list[dict]] = {}
    for train_no, stops in train_stops.items():
        for i in range(len(stops) - 1):
            from_tc, from_dep = stops[i]
            for j in range(i + 1, len(stops)):
                to_tc, to_arr = stops[j]
                adjacency.setdefault(from_tc, []).append(
                    {"to": to_tc, "train": train_no, "depart": from_dep, "arrive": to_arr}
                )

    # 去重: 同一 from→to 可能有多条车次, 保留最早到达
    deduped = {}
    for from_tc, edges in adjacency.items():
        best: dict[str, dict] = {}
        for e in edges:
            key = e["to"]
            if key not in best:
                best[key] = e
            else:
                if e["arrive"] < best[key]["arrive"]:
                    best[key] = e
        deduped[from_tc] = list(best.values())

    _write("adjacency.json", deduped)
    print(f"  adjacency.json — {len(deduped)} 个出发站节点")
    conn.close()


def export_all(hubs=None, spokes=None):
    """导出全部整理好的 JSON 文件."""
    print("导出 JSON 文件:")
    os.makedirs(DATA_DIR, exist_ok=True)
    export_stations()
    if hubs and spokes:
        export_hubs_and_spokes(hubs, spokes)
    export_trains()
    export_adjacency()
    print("完成")


def _write(filename: str, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
