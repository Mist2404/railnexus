"""Phase 1: 站点数据采集

解析 12306 station_name.js，提取全国所有客运站信息。
筛选出枢纽站和辐射站供 Phase 2 使用。
"""

import json
import httpx

from config import STATION_NAME_URL, STATIONS_JSON
from config import HUB_TELECODES, PREFECTURE_CITIES, HUB_STATIONS
from crawler.db import get_conn


def _parse_station_line(line: str) -> dict | None:
    """解析 station_name.js 中的一条站点数据.

    格式: @pinyin_abbr|name|telecode|pinyin|pinyin_abbr|id|area_code|city|...
    例如: @bjb|北京北|VAP|beijingbei|bjb|0|0357|北京
    """
    line = line.strip()
    if not line.startswith("@"):
        return None
    parts = line[1:].split("|")
    if len(parts) < 8:
        return None
    return {
        "abbr": parts[0].strip(),
        "name": parts[1].strip(),
        "telecode": parts[2].strip(),
        "pinyin": parts[3].strip(),
        "pinyin_short": parts[4].strip(),
        "city": parts[7].strip(),
    }


def _match_city(station_name: str, city_field: str) -> str:
    """站名含地级市名才算该市辐射站 (过滤下属县域站)."""
    for city in PREFECTURE_CITIES:
        if city in station_name:
            return city
    return ""


async def fetch_all_stations() -> list[dict]:
    """下载并解析全部站点, 返回 station dict 列表."""
    async with httpx.AsyncClient(http2=True, timeout=30) as client:
        resp = await client.get(STATION_NAME_URL)
        resp.raise_for_status()
        text = resp.text

    # 提取单引号之间的内容 (如: var station_names ='@bjb|...@bjd|...')
    # 格式: @pinyin_abbr|name|telecode|pinyin|pinyin_abbr|id|area_code|city|||
    stations = []
    for part in text.split("@"):
        part = part.strip()
        if not part or "|" not in part:
            continue
        # 去除结尾的引号和分号
        part = part.rstrip("';\"")
        s = _parse_station_line("@" + part)
        if s:
            stations.append(s)

    # 保存到 JSON
    with open(STATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(stations, f, ensure_ascii=False, indent=2)

    # 写入数据库
    conn = get_conn()
    conn.execute("DELETE FROM stations")
    conn.executemany(
        "INSERT OR REPLACE INTO stations (id, name, telecode, pinyin, abbr, city) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (i, s["name"], s["telecode"], s["pinyin"], s["abbr"], s["city"])
            for i, s in enumerate(stations)
        ],
    )
    conn.commit()
    conn.close()

    return stations


def _is_passenger_station(name: str) -> bool:
    """过滤非客运站: 线路所、乘降所、货场、车辆段等."""
    if not name:
        return False
    if name.endswith("所"):
        return False
    if "线路" in name or "乘降" in name:
        return False
    if "货场" in name or "货" in name[:-1]:
        return False
    if "编组" in name or "车辆段" in name or "机务" in name:
        return False
    return True


def classify_stations(all_stations: list[dict]) -> tuple[list[dict], list[dict]]:
    """将站点分类为枢纽站和辐射站.

    - 枢纽站: telecode 在 HUB_TELECODES 中 或 name 在 HUB_NAMES 中
    - 辐射站: city/name 匹配 PREFECTURE_CITIES, 同一城市保留全部客运站
    """
    from config import HUB_STATIONS
    HUB_NAMES = {h["name"] for h in HUB_STATIONS}

    hub_stations = []
    spoke_candidates = []

    seen_hub_names: set[str] = set()
    for s in all_stations:
        if s["telecode"] in HUB_TELECODES or s["name"] in HUB_NAMES:
            if _is_passenger_station(s["name"]) and s["name"] not in seen_hub_names:
                hub_stations.append(s)
                seen_hub_names.add(s["name"])
            continue
        city_match = _match_city(s["name"], s["city"])
        if city_match and _is_passenger_station(s["name"]):
            spoke_candidates.append(s)

    # 按 telecode 去重 (同一电报码不重复), 同一城市所有客运站全保留
    spoke_stations = []
    seen_tc: set[str] = set()
    for s in spoke_candidates:
        if s["telecode"] not in seen_tc:
            spoke_stations.append(s)
            seen_tc.add(s["telecode"])

    # 确保枢纽站按 HUB_STATIONS 定义的优先顺序排列
    hub_by_name = {s["name"]: s for s in hub_stations}
    hub_by_tc = {s["telecode"]: s for s in hub_stations}
    ordered_hubs = []
    seen_ordered: set[str] = set()
    for h in HUB_STATIONS:
        s = hub_by_tc.get(h["telecode"]) or hub_by_name.get(h["name"])
        if s and s["name"] not in seen_ordered:
            ordered_hubs.append(s)
            seen_ordered.add(s["name"])
    for s in hub_stations:
        if s["name"] not in seen_ordered:
            ordered_hubs.append(s)

    return ordered_hubs, spoke_stations
