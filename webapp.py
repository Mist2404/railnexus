"""RailNexus 换乘查询 Web 服务

基于 FastAPI, 复用 transfer.py 引擎.
启动: python webapp.py
访问: http://localhost:8000
"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from transfer import build_indexes, search, format_minutes

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="RailNexus", description="中国铁路换乘查询")

# 允许前端独立部署时跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局索引, 启动时加载一次
_IDX = None


def get_index():
    global _IDX
    if _IDX is None:
        _IDX = build_indexes()
    return _IDX


@app.on_event("startup")
def _startup():
    get_index()


class SearchRequest(BaseModel):
    from_station: str
    to_station: str
    depart: str = "00:00"


def _format_route(r: dict) -> dict:
    """把引擎返回的 route 转为前端友好的精简结构."""
    segs = [
        {
            "train": s["train_number"],
            "from": s["from_station"],
            "to": s["to_station"],
            "depart": s["depart_time"],
            "arrive": s["arrive_time"],
        }
        for s in r["segments"]
    ]
    return {
        "segments": segs,
        "transfer_count": r["transfer_count"],
        "total_duration": format_minutes(r["total_duration"]),
        "total_wait": format_minutes(r["total_wait"]),
    }


@app.get("/api/stations")
def list_stations(q: str = ""):
    """站名自动补全: 前缀匹配优先, 其次子串匹配."""
    idx = get_index()
    name_to_tc = idx["name_to_tc"]
    q = q.strip()
    if not q:
        return []

    prefix = []
    substring = []
    for name, tc in name_to_tc.items():
        if name.startswith(q):
            prefix.append({"name": name, "tc": tc})
        elif q in name:
            substring.append({"name": name, "tc": tc})

    results = prefix + substring
    return results[:12]


@app.post("/api/search")
def do_search(req: SearchRequest):
    result = search(
        req.from_station,
        req.to_station,
        req.depart,
    )
    if "error" in result:
        return {"error": result["error"], "hint": result.get("hint", "")}

    return {
        "direct": [_format_route(r) for r in result["direct"]],
        "one_transfer": [_format_route(r) for r in result["one_transfer"]],
        "two_transfer": [_format_route(r) for r in result["two_transfer"]],
    }


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
