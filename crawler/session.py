"""HTTP 会话管理 —— 模拟浏览器 Cookie/Headers"""

import httpx
from config import USER_AGENT, INIT_URL


def build_headers(referer: str = INIT_URL) -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": referer,
        "Origin": "https://kyfw.12306.cn",
        "Connection": "keep-alive",
    }


async def create_session() -> httpx.AsyncClient:
    """创建带 Cookie 的 HTTP 会话 (HTTP/2 多路复用)."""
    client = httpx.AsyncClient(http2=True, headers=build_headers(), timeout=30)

    try:
        resp = await client.get(INIT_URL)
        resp.raise_for_status()
    except Exception:
        pass

    return client
