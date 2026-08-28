"""导出地图数据 map_data.json

结构:
{
  "cities":  [{"name","lat","lng","station_tcs":[...]}],       # 城市级 (方案 A+ 第一级)
  "stations":[{"tc","name","lat","lng","level","city"}],        # 站点级 (方案 A+ 第二级)
  "edges":   [{"f","t","types":["G","D"]}]                     # 铁路网边 (相邻停站对)
}
"""

import json
import os
import sqlite3
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import DB_PATH
from crawler.coords import station_coords, get_city_center

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUT_PATH = os.path.join(DATA_DIR, "map_data.json")


def _load():
    conn = sqlite3.connect(DB_PATH)
    stations = conn.execute(
        "SELECT name, telecode, city FROM stations"
    ).fetchall()
    # 车次类型: train_no -> train_type
    train_type = dict(conn.execute(
        "SELECT train_no, train_type FROM trains"
    ).fetchall())
    # 停站: train_no -> [(seq, telecode)]
    rows = conn.execute(
        "SELECT train_no, seq, station_telecode FROM train_stops ORDER BY train_no, seq"
    ).fetchall()
    conn.close()
    return stations, train_type, rows


def build_map_data():
    stations, train_type, stop_rows = _load()

    # 1. 站点坐标
    station_info = {}          # tc -> {name, lat, lng, city}
    city_meta = defaultdict(list)  # city -> [tc, ...]
    for name, tc, city in stations:
        coord = station_coords(name, city or "")
        if coord is None:
            continue
        lat, lng = coord
        station_info[tc] = {"tc": tc, "name": name, "lat": lat, "lng": lng, "city": city}
        if city:
            city_meta[city].append(tc)

    # 2. 站点分级: 按途经车次数
    train_count = defaultdict(int)
    for tn, seq, tc in stop_rows:
        train_count[tc] += 1
    for tc, info in station_info.items():
        n = train_count.get(tc, 0)
        # level 1=枢纽(≥50), 2=地级(≥10), 3=小站(<10)
        info["level"] = 1 if n >= 50 else (2 if n >= 10 else 3)

    # 3. 城市级数据 (有坐标站点的城市)
    cities = []
    seen_city = set()
    for city, tcs in city_meta.items():
        if city in seen_city:
            continue
        seen_city.add(city)
        center = get_city_center(city)
        if center is None:
            continue
        # 只保留有坐标的站
        valid_tcs = [tc for tc in tcs if tc in station_info]
        if not valid_tcs:
            continue
        cities.append({
            "name": city,
            "lat": center[0],
            "lng": center[1],
            "station_tcs": valid_tcs,
        })

    # 4. 铁路网边: 相邻停站对 (去重, 记录车次类型)
    edges_map = defaultdict(set)  # (from_tc, to_tc) -> set(types)
    cur_train = None
    prev_tc = None
    for tn, seq, tc in stop_rows:
        if tn != cur_train:
            cur_train = tn
            prev_tc = None
            continue
        if prev_tc is not None and prev_tc in station_info and tc in station_info:
            key = (prev_tc, tc)
            ttype = train_type.get(tn, "")[:1]
            if ttype:
                edges_map[key].add(ttype)
        prev_tc = tc

    edges = [
        {"f": f, "t": t, "types": sorted(types)}
        for (f, t), types in edges_map.items()
    ]

    data = {
        "cities": cities,
        "stations": list(station_info.values()),
        "edges": edges,
    }
    return data


def export_map(force: bool = False):
    if os.path.exists(OUT_PATH) and not force:
        return
    data = build_map_data()
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"  map_data.json: {len(data['cities'])} cities, "
          f"{len(data['stations'])} stations, {len(data['edges'])} edges")


if __name__ == "__main__":
    export_map(force=True)
