"""铁路换乘查询引擎

基于 implement.md 的 Filter-and-Refine 算法:
  - Phase 1: 空间过滤 (倒排索引 + 集合求交)
  - Phase 2: 时序精炼 (二分查找 + 防逆行)
"""

import sqlite3
import json
import os
import pickle
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

# ===== 配置 =====
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "railway.db")
CACHE_PATH = os.path.join(os.path.dirname(__file__), "data", "index_cache.pkl")
MIN_TRANSFER_WAIT = 20  # 同站换乘最少预留分钟数
MAX_RESULTS_PER_TIER = 20  # 每种换乘等级最多保留条数


@dataclass
class Segment:
    train_no: str
    train_number: str
    from_station: str          # 站名
    from_telecode: str
    to_station: str
    to_telecode: str
    depart_time: str           # "HH:MM"
    arrive_time: str
    depart_abs: int            # 绝对分钟
    arrive_abs: int


@dataclass
class Route:
    segments: list[Segment] = field(default_factory=list)
    transfer_count: int = 0
    total_duration: int = 0    # 总行程分钟 (不含换乘等待)
    total_wait: int = 0        # 换乘等待总分钟

    def format_duration(self, mins: int) -> str:
        h, m = divmod(mins, 60)
        return f"{h}h{m:02d}m" if h else f"{m}m"

    def summary(self) -> str:
        parts = []
        for seg in self.segments:
            parts.append(
                f"{seg.train_number}({seg.from_station}→{seg.to_station} "
                f"{seg.depart_time}-{seg.arrive_time})"
            )
        dur = self.format_duration(self.total_duration)
        if self.transfer_count == 0:
            return f"[直达 {dur}] {' | '.join(parts)}"
        wait = self.format_duration(self.total_wait)
        return f"[{self.transfer_count}换乘 {dur} 等{wait}] {' | '.join(parts)}"


# ===== 索引构建 =====

def _to_abs_minutes(time_str: str, day_offset: int = 0) -> Optional[int]:
    """将 "HH:MM" 或 "----" 转换为绝对分钟数."""
    if not time_str or time_str == "----":
        return None
    parts = time_str.strip().split(":")
    if len(parts) == 2:
        try:
            return day_offset * 1440 + int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    return None


def _to_time_str(abs_minutes: int) -> str:
    """绝对分钟转回 "HH:MM" 格式."""
    day_minutes = abs_minutes % 1440
    h, m = divmod(day_minutes, 60)
    return f"{h:02d}:{m:02d}"


def build_indexes(force: bool = False):
    """从 railway.db 构建 S2T, T2S, Timetable, SDI 四个索引, 并缓存到 pickle."""
    if not force and os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            return pickle.load(f)

    conn = sqlite3.connect(DB_PATH)

    # 加载站名 → 电报码
    name_to_tc = {}
    tc_to_name = {}
    for name, tc in conn.execute("SELECT name, telecode FROM stations").fetchall():
        name_to_tc[name] = tc
        tc_to_name[tc] = name

    # 加载车次信息
    train_info = {}
    for row in conn.execute(
        "SELECT train_no, train_number, train_type FROM trains"
    ).fetchall():
        train_info[row[0]] = {"train_number": row[1], "train_type": row[2]}

    # 加载全部停站, 按车次+站序排序
    rows = conn.execute(
        "SELECT train_no, seq, station_telecode, arrive_time, depart_time, day_offset "
        "FROM train_stops ORDER BY train_no, seq"
    ).fetchall()
    conn.close()

    # --- 构建索引 ---
    S2T: dict[str, set[str]] = {}           # 站 → 途经车次集合
    T2S: dict[str, list[str]] = {}          # 车次 → 有序停站序列
    Timetable: dict[tuple[str, str], tuple[int, int]] = {}  # (车次, 站) → (到达绝对分钟, 发车绝对分钟)
    SDI_raw: dict[str, list[tuple[str, int]]] = {}  # 站 → [(车次, 发车绝对分钟), ...]

    # 预处理: 按车次分组, 自行推断跨日偏移 (DB 存的不准)
    train_rows: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        train_rows[row[0]].append(row)

    for train_no, stops in train_rows.items():
        first_tc = stops[0][2]  # 始发站 telecode
        S2T.setdefault(first_tc, set()).add(train_no)
        T2S.setdefault(train_no, [])
        day = 0
        prev_dep: Optional[int] = None

        for _, seq, tc, arr, dep, _db_day_off in stops:
            T2S[train_no].append(tc)
            S2T.setdefault(tc, set()).add(train_no)

            arr_loc = _to_abs_minutes(arr, 0)
            dep_loc = _to_abs_minutes(dep, 0)

            # 跨日1: 列车行进中跨越午夜 (本站到达时间早于前站发车)
            if prev_dep is not None and arr_loc is not None and arr_loc < prev_dep:
                day += 1

            arr_abs = _to_abs_minutes(arr, day) if arr_loc is not None else None

            # 跨日2: 在本站停靠跨越午夜 (如 23:50到/00:01发)
            if arr_loc is not None and dep_loc is not None and dep_loc < arr_loc:
                day += 1

            dep_abs = _to_abs_minutes(dep, day) if dep_loc is not None else None

            if dep_loc is not None:
                prev_dep = dep_loc

            if arr_abs is not None or dep_abs is not None:
                Timetable[(train_no, tc)] = (arr_abs, dep_abs)

            if dep_abs is not None:
                SDI_raw.setdefault(tc, []).append((train_no, dep_abs))

    # 构建排序后的 SDI
    SDI: dict[str, list[tuple[str, int]]] = {}
    for tc, events in SDI_raw.items():
        SDI[tc] = sorted(events, key=lambda x: x[1])

    indexes = {
        "name_to_tc": name_to_tc,
        "tc_to_name": tc_to_name,
        "train_info": train_info,
        "S2T": S2T,
        "T2S": T2S,
        "Timetable": Timetable,
        "SDI": SDI,
    }

    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(indexes, f, protocol=pickle.HIGHEST_PROTOCOL)

    return indexes


# ===== 查询入口 =====

def _compute_wait(prev_arr_global: int, next_dep_local: int, min_wait: int) -> tuple[int, int]:
    """日历正确的衔接等待时间.

    prev_arr_global:  前段到达的全局绝对分钟
    next_dep_local:   后段发车的本地时间 (0-1439)
    min_wait:         最少换乘等待分钟

    Returns: (wait_minutes, dep_global)
    
    自动寻找最小 N 使得 next_dep_local + N*1440 >= prev_arr_global + min_wait.
    """
    need = prev_arr_global + min_wait
    if next_dep_local >= need:
        return next_dep_local - prev_arr_global, next_dep_local
    N = (need - next_dep_local + 1439) // 1440  # ceil division
    dep_global = next_dep_local + N * 1440
    return dep_global - prev_arr_global, dep_global


def _is_redundant(idx, t1, t_mid, t2, from_tc, m1, m2, to_tc) -> bool:
    """判断换乘方案是否被更短方案等价覆盖.

    t_mid 为 None 时按 1 次换乘判定; 否则按 2 次换乘判定.
    满足任一规则即冗余, 调用方应直接丢弃该方案.
    """
    T2S = idx["T2S"]
    st1 = T2S.get(t1, [])
    st2 = T2S.get(t2, [])

    def passes(stops, a, b):
        return a in stops and b in stops and stops.index(a) < stops.index(b)

    # 1 次换乘: t1 直达终点, 或 t2 从起点即可上车
    if t_mid is None:
        return passes(st1, from_tc, to_tc) or passes(st2, from_tc, m1)

    # 2 次换乘: 6 条规则全查
    stm = T2S.get(t_mid, [])
    return (
        passes(st1, from_tc, to_tc) or   # t1 直达
        passes(st2, from_tc, m2) or      # t2 经过起点 → 直达
        passes(stm, from_tc, m1) or      # t_mid 经过起点 → 等价 1 次换乘 (t_mid+t2)
        passes(stm, m2, to_tc) or        # t_mid 到终点 → 等价 1 次换乘 (t1+t_mid)
        passes(st1, m1, m2) or           # t1 经过 m2 → 等价 1 次换乘 (t1+t2)
        passes(st2, m1, m2)              # t2 经过 m1 → 等价 1 次换乘 (t1+t2)
    )

def _station_not_found(name: str, name_to_tc: dict) -> dict:
    """模糊匹配站名建议."""
    suggestions = [n for n in name_to_tc if name in n][:8]
    return {
        "error": f"未找到车站: {name}",
        "hint": f"同城可选: {', '.join(suggestions)}" if suggestions else "请检查站名",
    }


def _find_nearby_stations(idx: dict, name: str) -> str:
    """返回同城有车次的站."""
    name_to_tc = idx["name_to_tc"]
    tc_to_name = idx["tc_to_name"]
    S2T = idx["S2T"]
    tc = name_to_tc.get(name, "")
    if not tc:
        return ""
    city_tcs = [tc for tc, n in tc_to_name.items() if name[:2] in n and S2T.get(tc)]
    nearby = [tc_to_name.get(t, t) for t in city_tcs[:5]]
    return f"同城有车次站: {', '.join(nearby)}" if nearby else ""

def search(
    from_station: str,
    to_station: str,
    depart_time: str = "00:00",
    min_wait: int = MIN_TRANSFER_WAIT,
    max_per_tier: int = MAX_RESULTS_PER_TIER,
) -> dict:
    """主查询入口.

    Args:
        from_station: 出发站名
        to_station:   目的站名
        depart_time:  最早出发时间 "HH:MM"
        min_wait:     换乘最少预留分钟
        max_per_tier: 每种换乘等级返回上限

    Returns:
        {"direct": [...], "one_transfer": [...], "two_transfer": [...]}
    """
    idx = build_indexes()
    name_to_tc = idx["name_to_tc"]
    tc_to_name = idx["tc_to_name"]

    from_tc = name_to_tc.get(from_station)
    to_tc = name_to_tc.get(to_station)

    if not from_tc:
        return _station_not_found(from_station, name_to_tc)
    if not to_tc:
        return _station_not_found(to_station, name_to_tc)

    # 检查是否有途经车次
    if not idx["S2T"].get(from_tc):
        nearby = _find_nearby_stations(idx, from_station)
        return {"error": f"出发站 {from_station}({from_tc}) 无途经车次", "hint": nearby}
    if not idx["S2T"].get(to_tc):
        nearby = _find_nearby_stations(idx, to_station)
        return {"error": f"目的站 {to_station}({to_tc}) 无途经车次", "hint": nearby}

    earliest_depart = _to_abs_minutes(depart_time)

    # 0 次换乘
    direct = _find_direct(idx, from_tc, to_tc, earliest_depart, max_per_tier)

    # 1 次换乘
    one = _find_one_transfer(idx, from_tc, to_tc, earliest_depart, min_wait, max_per_tier)

    # 2 次换乘
    two = _find_two_transfer(idx, from_tc, to_tc, earliest_depart, min_wait, max_per_tier)

    return {
        "direct": direct,
        "one_transfer": one,
        "two_transfer": two,
    }


# ===== 0 次换乘: 直达 =====

def _find_direct(idx, from_tc, to_tc, earliest: int, limit: int) -> list[dict]:
    """直达: S2T(from) ∩ S2T(to) + 方向 + 时间校验."""
    S2T = idx["S2T"]
    T2S = idx["T2S"]
    Timetable = idx["Timetable"]
    tc_to_name = idx["tc_to_name"]
    train_info = idx["train_info"]

    from_trains = S2T.get(from_tc, set())
    to_trains = S2T.get(to_tc, set())
    candidates = from_trains & to_trains

    results = []
    for train_no in candidates:
        stops = T2S.get(train_no, [])
        if from_tc not in stops or to_tc not in stops:
            continue
        from_idx = stops.index(from_tc)
        to_idx = stops.index(to_tc)
        if from_idx >= to_idx:
            continue  # 逆行

        tt_from = Timetable.get((train_no, from_tc))
        tt_to = Timetable.get((train_no, to_tc))
        if not tt_from or not tt_to:
            continue

        _, dep_from = tt_from
        arr_to, _ = tt_to
        if dep_from is None or arr_to is None:
            continue
        if dep_from < earliest:
            continue

        results.append(_make_direct_route(idx, train_no, from_tc, to_tc, dep_from, arr_to))

    # 按发车时间排序
    results.sort(key=lambda r: r["segments"][0]["depart_abs"])
    return results[:limit]


def _make_direct_route(idx, train_no, from_tc, to_tc, dep_abs, arr_abs) -> dict:
    info = idx["train_info"].get(train_no, {})
    tc_to_name = idx["tc_to_name"]
    return {
        "segments": [{
            "train_no": train_no,
            "train_number": info.get("train_number", ""),
            "from_station": tc_to_name.get(from_tc, from_tc),
            "from_telecode": from_tc,
            "to_station": tc_to_name.get(to_tc, to_tc),
            "to_telecode": to_tc,
            "depart_time": _to_time_str(dep_abs),
            "arrive_time": _to_time_str(arr_abs),
            "depart_abs": dep_abs,
            "arrive_abs": arr_abs,
        }],
        "transfer_count": 0,
        "total_duration": arr_abs - dep_abs,
        "total_wait": 0,
    }


# ===== 1 次换乘 =====

def _find_one_transfer(
    idx, from_tc, to_tc, earliest: int, min_wait: int, limit: int
) -> list[dict]:
    """一次换乘: 空间求交换乘站 + 二分查找合法前后序车."""
    S2T = idx["S2T"]
    T2S = idx["T2S"]
    Timetable = idx["Timetable"]
    SDI = idx["SDI"]
    tc_to_name = idx["tc_to_name"]
    train_info = idx["train_info"]

    # 1. 从起点出发的所有车次的一阶可达站
    V_start: set[str] = set()
    for train_no in S2T.get(from_tc, set()):
        stops = T2S.get(train_no, [])
        if from_tc in stops:
            start_idx_stop = stops.index(from_tc)
            for s in stops[start_idx_stop + 1:]:
                tt = Timetable.get((train_no, s))
                if tt and tt[1] is not None:
                    V_start.add(s)

    # 2. 能到达终点的所有车次的逆向可达站
    V_end: set[str] = set()
    for train_no in S2T.get(to_tc, set()):
        stops = T2S.get(train_no, [])
        if to_tc in stops:
            end_idx_stop = stops.index(to_tc)
            for s in stops[:end_idx_stop]:
                tt = Timetable.get((train_no, s))
                if tt and tt[1] is not None:
                    V_end.add(s)

    # 3. 候选换乘站 (排除只有单趟车停靠的站: 同车直达不算换乘, 不可能产生方案)
    candidates = {
        m for m in (V_start & V_end)
        if len(S2T.get(m, set())) >= 2
    }
    if not candidates:
        return []

    # 4. 时序验证
    results = []
    # 建立终点侧车次的倒排: 站 → 哪些车次可以到终站
    end_trains_at: dict[str, set[str]] = {}
    for train_no in S2T.get(to_tc, set()):
        stops = T2S.get(train_no, [])
        if to_tc in stops:
            end_idx = stops.index(to_tc)
            for s in stops[:end_idx]:
                tt = Timetable.get((train_no, s))
                if tt and tt[1] is not None:
                    end_trains_at.setdefault(s, set()).add(train_no)

    for m_tc in candidates:
        sdi = SDI.get(m_tc)
        if not sdi:
            continue

        # 遍历所有从起点出发经过 m_tc 的车次
        for t1 in S2T.get(from_tc, set()):
            stops1 = T2S.get(t1, [])
            if from_tc not in stops1 or m_tc not in stops1:
                continue
            if stops1.index(from_tc) >= stops1.index(m_tc):
                continue  # 逆行

            tt1_depart = Timetable.get((t1, from_tc))
            tt1_arrive = Timetable.get((t1, m_tc))
            if not tt1_depart or not tt1_arrive:
                continue
            _, dep1 = tt1_depart       # departure from from_tc
            arr1_m, _ = tt1_arrive     # arrival at m_tc
            if dep1 is None or arr1_m is None:
                continue
            if dep1 < earliest:
                continue

            # 接续时间边界 (SDI 存本地时间, 所以取模)
            limit_time = (arr1_m + min_wait) % 1440

            # 二分查找 m_tc 站最早发车 ≥ limit_time 的车次
            dep_list = [e[1] for e in sdi]
            pos = bisect_left(dep_list, limit_time)
            if pos >= len(sdi):
                continue

            # 遍历 pos 之后的所有车次, 检查是否能到达终点
            end_set = end_trains_at.get(m_tc, set())
            found = 0
            for i in range(pos, len(sdi)):
                t2 = sdi[i][0]
                _ = sdi[i][1]  # dep_local (仅用于二分, 实际时间用 Timetable)
                if t2 not in end_set:
                    continue
                if t2 == t1:
                    continue

                # 用 Timetable 取值 (包含车次内部的 day_offset)
                tt2_m = Timetable.get((t2, m_tc))
                tt2_to = Timetable.get((t2, to_tc))
                if not tt2_m or not tt2_to:
                    continue
                _, dep2_abs_train = tt2_m
                arr2_abs_train, _ = tt2_to
                if dep2_abs_train is None or arr2_abs_train is None:
                    continue

                # 日历正确衔接: 计算等待 + 全局发车时间
                dep2_local = dep2_abs_train % 1440
                wait, dep2_global = _compute_wait(arr1_m, dep2_local, min_wait)
                shift = dep2_global - dep2_abs_train
                arr2_global = arr2_abs_train + shift
                total_dur = arr2_global - dep1

                # 剔除冗余: 被更短方案等价覆盖 (t1 直达 或 t2 经过起点)
                if _is_redundant(idx, t1, None, t2, from_tc, m_tc, None, to_tc):
                    continue

                route = {
                    "segments": [
                        _make_seg(idx, t1, from_tc, m_tc, dep1, arr1_m),
                        _make_seg(idx, t2, m_tc, to_tc, dep2_global, arr2_global),
                    ],
                    "transfer_count": 1,
                    "total_duration": total_dur,
                    "total_wait": wait,
                }
                results.append(route)

                # 适度剪枝: 每个换乘站最多取 10 个合法后序方案
                found += 1
                if found >= 10:
                    break

    # 按总耗时排序
    results.sort(key=lambda r: r["total_duration"])
    return results[:limit]


# ===== 2 次换乘 =====

def _find_two_transfer(
    idx, from_tc, to_tc, earliest: int, min_wait: int, limit: int
) -> list[dict]:
    """两次换乘: 车次空间求交找中间车次 + 链式时序."""
    S2T = idx["S2T"]
    T2S = idx["T2S"]
    Timetable = idx["Timetable"]
    SDI = idx["SDI"]
    train_info = idx["train_info"]

    # 1. 起点一阶辐射
    trains_from_start: set[str] = set()
    V_start: set[str] = set()
    for train_no in S2T.get(from_tc, set()):
        stops = T2S.get(train_no, [])
        if from_tc in stops:
            trains_from_start.add(train_no)
            si = stops.index(from_tc)
            for s in stops[si + 1:]:
                tt = Timetable.get((train_no, s))
                if tt and tt[1] is not None:
                    V_start.add(s)

    # 2. 终点一阶辐射
    trains_to_end: set[str] = set()
    V_end: set[str] = set()
    end_trains_at: dict[str, set[str]] = {}
    for train_no in S2T.get(to_tc, set()):
        stops = T2S.get(train_no, [])
        if to_tc in stops:
            trains_to_end.add(train_no)
            ei = stops.index(to_tc)
            for s in stops[:ei]:
                tt = Timetable.get((train_no, s))
                if tt and tt[1] is not None:
                    V_end.add(s)
                    end_trains_at.setdefault(s, set()).add(train_no)

    # 3. 中间车次: 同时经过 V_start 和 V_end (排除首尾)
    mid_from = set.union(set(), *(S2T.get(s, set()) for s in V_start))
    mid_to = set.union(set(), *(S2T.get(s, set()) for s in V_end))
    T_mid = (mid_from & mid_to) - trains_from_start - trains_to_end

    if not T_mid:
        return []

    # 4. 处理每个中间车次
    results: list[dict] = []
    for t_mid in T_mid:
        stops_mid = T2S.get(t_mid, [])
        # 排除单趟车停靠的站 (前段/后段车必与中间车不同, 故需 ≥2 趟车)
        m1_candidates = [
            s for s in stops_mid
            if s in V_start and len(S2T.get(s, set())) >= 2
        ]
        m2_candidates = [
            s for s in stops_mid
            if s in V_end and len(S2T.get(s, set())) >= 2
        ]
        if not m1_candidates or not m2_candidates:
            continue

        m1_candidates = m1_candidates[:3]
        m2_candidates = m2_candidates[-3:]
        for m1 in m1_candidates:
            idx_m1 = stops_mid.index(m1)
            for m2 in m2_candidates:
                idx_m2 = stops_mid.index(m2)
                if idx_m1 >= idx_m2:
                    continue

                # 第一段: from_tc → m1
                for t1 in trains_from_start:
                    tt1_dep = Timetable.get((t1, from_tc))
                    tt1_arr = Timetable.get((t1, m1))
                    if not tt1_dep or not tt1_arr:
                        continue
                    _, dep1 = tt1_dep
                    arr1_m1, _ = tt1_arr
                    if dep1 is None or arr1_m1 is None or dep1 < earliest:
                        continue
                    if T2S[t1].index(from_tc) >= T2S[t1].index(m1):
                        continue

                    tt_mid_m1 = Timetable.get((t_mid, m1))
                    if not tt_mid_m1:
                        continue
                    _, dep_mid_train = tt_mid_m1
                    if dep_mid_train is None:
                        continue

                    dep_mid_local = dep_mid_train % 1440
                    wait_1, dep_mid_global = _compute_wait(arr1_m1, dep_mid_local, min_wait)
                    shift_mid = dep_mid_global - dep_mid_train

                    tt_mid_m2 = Timetable.get((t_mid, m2))
                    if not tt_mid_m2:
                        continue
                    arr_mid_train, _ = tt_mid_m2
                    if arr_mid_train is None:
                        continue
                    arr_mid_global = arr_mid_train + shift_mid

                    # 衔接 2: arr_mid_global → t2@m2
                    sdi_m2 = SDI.get(m2)
                    if not sdi_m2:
                        continue
                    limit_2 = (arr_mid_global + min_wait) % 1440
                    dep_list = [e[1] for e in sdi_m2]
                    pos = bisect_left(dep_list, limit_2)
                    if pos >= len(sdi_m2):
                        continue

                    end_set = end_trains_at.get(m2, set())
                    found = 0
                    for i in range(pos, min(pos + 8, len(sdi_m2))):
                        t2 = sdi_m2[i][0]
                        if t2 not in end_set or t2 == t1 or t2 == t_mid:
                            continue
                        tt2_m2 = Timetable.get((t2, m2))
                        tt2_to = Timetable.get((t2, to_tc))
                        if not tt2_m2 or not tt2_to:
                            continue
                        _, dep2_train = tt2_m2
                        arr2_train, _ = tt2_to
                        if dep2_train is None or arr2_train is None:
                            continue

                        dep2_local = dep2_train % 1440
                        wait_2, dep2_global = _compute_wait(arr_mid_global, dep2_local, min_wait)
                        shift_2 = dep2_global - dep2_train
                        arr2_global = arr2_train + shift_2

                        total_dur = arr2_global - dep1
                        # 剔除冗余: 被直达或 1 次换乘方案等价覆盖
                        if _is_redundant(idx, t1, t_mid, t2, from_tc, m1, m2, to_tc):
                            continue
                        results.append({
                            "segments": [
                                _make_seg(idx, t1, from_tc, m1, dep1, arr1_m1),
                                _make_seg(idx, t_mid, m1, m2, dep_mid_global, arr_mid_global),
                                _make_seg(idx, t2, m2, to_tc, dep2_global, arr2_global),
                            ],
                            "transfer_count": 2,
                            "total_duration": total_dur,
                            "total_wait": wait_1 + wait_2,
                        })
                        found += 1
                        if found >= 3:
                            break

                    break  # 每个 (m1,m2) 只取一个 t1

    results.sort(key=lambda r: r["total_duration"])
    return results[:limit]


# ===== 辅助函数 =====

def _make_seg(idx, train_no, from_tc, to_tc, dep_abs, arr_abs) -> dict:
    info = idx["train_info"].get(train_no, {})
    tc_to_name = idx["tc_to_name"]
    return {
        "train_no": train_no,
        "train_number": info.get("train_number", ""),
        "from_station": tc_to_name.get(from_tc, from_tc),
        "from_telecode": from_tc,
        "to_station": tc_to_name.get(to_tc, to_tc),
        "to_telecode": to_tc,
        "depart_time": _to_time_str(dep_abs),
        "arrive_time": _to_time_str(arr_abs),
        "depart_abs": dep_abs,
        "arrive_abs": arr_abs,
    }


def format_minutes(mins: int) -> str:
    h, m = divmod(mins, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m"


# ===== CLI =====

if __name__ == "__main__":
    import sys
    import time

    if len(sys.argv) < 3:
        print("用法: python transfer.py <出发站> <到达站> [最早出发时间] [--json]")
        print("示例: python transfer.py 北京南 上海虹桥 08:00")
        print("      python transfer.py 成都东 乌鲁木齐 --json")
        sys.exit(1)

    frm = sys.argv[1]
    to = sys.argv[2]
    dep = "00:00"
    fmt_json = False
    for a in sys.argv[3:]:
        if a == "--json":
            fmt_json = True
        else:
            dep = a

    t0 = time.time()
    result = search(frm, to, dep)
    elapsed = time.time() - t0

    if "error" in result:
        print(f"错误: {result['error']}")
        if "hint" in result:
            print(f"提示: {result['hint']}")
        sys.exit(1)

    if fmt_json:
        # JSON 输出 (精简版, 不含 abs 分钟字段)
        out = {}
        for tier_name, tier_results in [
            ("direct", result["direct"]),
            ("one_transfer", result["one_transfer"]),
            ("two_transfer", result["two_transfer"]),
        ]:
            out[tier_name] = []
            for r in tier_results:
                segs = []
                for s in r["segments"]:
                    segs.append({
                        "train": s["train_number"],
                        "from": s["from_station"],
                        "to": s["to_station"],
                        "depart": s["depart_time"],
                        "arrive": s["arrive_time"],
                    })
                out[tier_name].append({
                    "segments": segs,
                    "transfer_count": r["transfer_count"],
                    "total_duration": format_minutes(r["total_duration"]),
                    "total_wait": format_minutes(r["total_wait"]),
                })
        out["query_time_s"] = round(elapsed, 2)
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        for tier_name, tier_results in [
            ("0 次换乘 (直达)", result["direct"]),
            ("1 次换乘", result["one_transfer"]),
            ("2 次换乘", result["two_transfer"]),
        ]:
            print(f"\n{'─' * 50}")
            print(f"  {tier_name} ({len(tier_results)} 条)")
            print(f"{'─' * 50}")
            for i, r in enumerate(tier_results, 1):
                segs = r["segments"]
                dur = format_minutes(r["total_duration"])
                wait = format_minutes(r["total_wait"])
                line = f"  [{i}] {dur}"
                if r["transfer_count"] > 0:
                    line += f" 换乘等待 {wait}"
                print(line)
                for s in segs:
                    print(
                        f"      {s['train_number']:6s} {s['from_station']} → {s['to_station']} "
                        f"{s['depart_time']} — {s['arrive_time']}"
                    )

        print(f"\n{'─' * 50}")
        print(f"  查询耗时: {elapsed:.2f}s")
        total = len(result["direct"]) + len(result["one_transfer"]) + len(result["two_transfer"])
        print(f"  共 {total} 条方案")
