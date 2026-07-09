"""健康探针路由：分级探测，供 K8s / Java 网关摘流用。

- /health/live   —— 极简心跳，只判进程存活。K8s liveness 用这个。
- /health/ready  —— 深度检查依赖（PG / LLM / Java API）。K8s readiness 用这个。
- /health        —— 综合视图，返回 200 + 各依赖状态，人肉排查用。

/live 永远返回 200（除非进程挂了）；/ready 任一关键依赖挂了返回 503，让流量
被网关摘走，等依赖恢复后再拉回来。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from agents.runtime import is_persistent
from core.config import config
from core.llm import get_llm

router = APIRouter(prefix="/health", tags=["health"])
logger = logging.getLogger("ai-service.health")

# 单次依赖检查超时。设短一点，避免 /ready 被慢依赖拖成雪崩。
_DEP_CHECK_TIMEOUT = 2.0


@router.get("/live")
async def live() -> dict[str, Any]:
    """进程存活探针。K8s liveness probe 用。

    只要 uvicorn worker 能处理请求就返 200，不查依赖。
    """
    return {"status": "alive"}


@router.get("/ready")
async def ready() -> Any:
    """就绪探针。K8s readiness probe / Java 网关健康检查用。

    检查所有关键依赖，任一挂了返 503，让流量被摘走。恢复后再拉回来。
    """
    checks = await _run_checks()
    ok = all(v.get("ok") for v in checks.values())
    body = {"status": "ready" if ok else "not-ready", "checks": checks}
    return JSONResponse(status_code=200 if ok else 503, content=body)


@router.get("")
async def summary() -> dict[str, Any]:
    """综合健康视图。永远返回 200，供人肉排查用。"""
    checks = await _run_checks()
    return {
        "status": "healthy" if all(v.get("ok") for v in checks.values()) else "degraded",
        "checks": checks,
    }


async def _run_checks() -> dict[str, dict]:
    """并发跑所有依赖检查。任何一个抛异常都视为该项失败。"""
    names = ["llm", "postgres", "java_api"]
    coros = [_check_llm(), _check_postgres(), _check_java_api()]
    results = await asyncio.gather(*coros, return_exceptions=True)
    out: dict[str, dict] = {}
    for name, r in zip(names, results):
        if isinstance(r, Exception):
            out[name] = {"ok": False, "error": str(r)}
        else:
            out[name] = r
    return out


async def _check_llm() -> dict:
    """LLM 只做 config 层面检查（是否有 API key）。真的打模型太贵不适合放 /ready。"""
    llm = get_llm()
    if llm is None:
        return {"ok": False, "error": "LLM not configured"}
    return {"ok": True, "provider": config.MODEL_PROVIDER, "model": config.LLM_MODEL}


async def _check_postgres() -> dict:
    """通过 runtime.is_persistent() 判断 PG 连接是否可用。

    init_runtime() 已经在启动时试过一次；连不上会走 InMemory 降级。
    这里再补一次实时查询以捕获运行时断连。
    """
    if not is_persistent():
        return {"ok": False, "mode": "in-memory-fallback",
                "error": "Postgres not connected, using in-memory fallback"}
    # 快速跑一个 SELECT 1，验证连接还活着
    try:
        from agents.runtime import _pg_conn  # type: ignore
        if _pg_conn is None:
            return {"ok": False, "error": "connection is None"}
        async with asyncio.timeout(_DEP_CHECK_TIMEOUT):
            async with _pg_conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
        return {"ok": True, "mode": "postgres"}
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout > {_DEP_CHECK_TIMEOUT}s"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


async def _check_java_api() -> dict:
    """Java 后端健康：调用 Java 侧 /api/health/live。

    路径挂在 /api/** 下，天然被 Java SecurityConfig 放行，无需 JWT。
    Java 返回 code=200 的 Result 结构 → JavaApiResult.success=True。
    """
    try:
        from core.java_api_client import get_java_api_client
        client = get_java_api_client()
        async with asyncio.timeout(_DEP_CHECK_TIMEOUT):
            result = await client.get("/api/health/live")
        # success 已经包含"HTTP 200 且 Java code=200"两层判断
        ok = bool(getattr(result, "success", False))
        return {
            "ok": ok,
            "endpoint": config.JAVA_API_BASE_URL,
            "status": (result.data.get("status") if ok and isinstance(result.data, dict) else None),
        }
    except asyncio.TimeoutError:
        return {"ok": False, "error": f"timeout > {_DEP_CHECK_TIMEOUT}s"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "endpoint": config.JAVA_API_BASE_URL}
