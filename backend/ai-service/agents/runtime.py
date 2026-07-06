"""LangGraph 记忆运行时：AsyncPostgresSaver + AsyncPostgresStore（连不上时回退 InMemory）。

- **checkpointer**：短期记忆，按 thread_id 保存整轮对话 messages
- **store**：长期记忆，跨 thread 存储业务记忆（商品卡、用户偏好等）

## 生命周期

主图用 async 接口调用（`await graph.ainvoke(...)`），因此必须使用 Async 变体。
Async 后端持有的连接绑定到创建时的 event loop —— 必须复用 uvicorn 主 loop，
不能在模块加载时用 `asyncio.run()` 初始化（那个 loop 用完就关）。

正确做法：**服务启动阶段调用 `await init_runtime()`**，在主 loop 内建立连接。
`main.py` 的 FastAPI lifespan 会调这个函数；测试脚本也可以手动 await。

初始化前访问 `checkpointer` / `store` 会拿到 InMemory 占位实例（安全兜底，
避免任何 import 顺序问题导致 AttributeError）。真实的持久化实例会在
`init_runtime()` 成功后覆盖这两个全局名。

## 降级策略

`init_runtime()` 内部 try/except：Postgres 连不上时保留 InMemory 占位，
日志给出警告。不阻断服务启动。

## Windows 兼容

psycopg async 模式在 Windows 上不支持默认的 ProactorEventLoop，
必须切换成 SelectorEventLoop。这一步在模块加载时立即做，早于任何
loop 创建，避免 uvicorn 已经拿到 Proactor 后再切换失败。
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Any
from urllib.parse import quote_plus

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from core.config import config

logger = logging.getLogger("ai-service.runtime")


# ---- Windows event loop 兼容 ----------------------------------------------
# psycopg async 不支持 Windows 默认的 ProactorEventLoop。
# 必须在 uvicorn 启动 event loop 之前切换 policy。
# 参考：https://www.psycopg.org/psycopg3/docs/advanced/async.html#async-support-on-windows
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ---- 连接串 --------------------------------------------------------------

def _build_pg_conn_string() -> str:
    """构造 PostgreSQL 连接串。connect_timeout=3 避免服务启动被拖住。"""
    password = quote_plus(config.PG_PASSWORD)
    return (
        f"postgresql://{config.PG_USER}:{password}"
        f"@{config.PG_HOST}:{config.PG_PORT}/{config.PG_NAME}"
        f"?sslmode=disable&connect_timeout=3"
    )


# ---- 全局单例 ------------------------------------------------------------
# 先初始化为 InMemory 占位。init_runtime() 成功后被 Postgres 后端覆盖。
# 用占位而非 None，避免任何模块（如 assistant/graph.py）在 init 完成前 import 时
# 拿到 None 崩溃。init 完成后所有名字引用会跟随全局绑定更新，因为主图在 lifespan
# 之后才构造。

checkpointer: Any = InMemorySaver()
store: Any = InMemoryStore()

_pg_conn = None            # AsyncConnection 实例（用于 checkpointer）
_pg_store_conn = None      # AsyncConnection 实例（用于 store，独立连接避免相互阻塞）
_using_postgres = False


async def init_runtime() -> bool:
    """在 event loop 内异步初始化 Postgres 后端。

    由 FastAPI lifespan 或测试脚本调用。多次调用是幂等的：
    首次成功后 _using_postgres=True，直接返回。

    Returns:
        True 表示成功用上 Postgres；False 表示降级 InMemory。
    """
    global checkpointer, store, _pg_conn, _pg_store_conn, _using_postgres

    if _using_postgres:
        return True

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg import AsyncConnection
        from psycopg.rows import dict_row
    except ImportError as e:
        logger.warning("langgraph-checkpoint-postgres 未安装，保留 InMemory: %s", e)
        return False

    conn_string = _build_pg_conn_string()

    try:
        # 建两个独立 async 连接，分别给 saver / store 用。
        # 参数照抄 from_conn_string 源码，确保行为一致。
        _pg_conn = await AsyncConnection.connect(
            conn_string,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        _pg_store_conn = await AsyncConnection.connect(
            conn_string,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )

        saver = AsyncPostgresSaver(conn=_pg_conn)
        await saver.setup()

        pg_store = AsyncPostgresStore(conn=_pg_store_conn)
        await pg_store.setup()

        checkpointer = saver
        store = pg_store
        _using_postgres = True
        logger.info("Using AsyncPostgresSaver + AsyncPostgresStore (db=%s)", config.PG_NAME)
        return True
    except Exception as e:
        logger.warning("PostgreSQL 连接失败，保留 InMemory: %s", e)
        await _close_pg_conns()
        return False


async def close_runtime() -> None:
    """关闭 Postgres 连接。由 FastAPI lifespan shutdown 调用。"""
    global _using_postgres
    if not _using_postgres:
        return
    await _close_pg_conns()
    _using_postgres = False
    logger.info("Postgres runtime closed")


async def _close_pg_conns() -> None:
    """关闭已开的连接（幂等）。"""
    global _pg_conn, _pg_store_conn
    for name in ("_pg_conn", "_pg_store_conn"):
        conn = globals()[name]
        if conn is None:
            continue
        try:
            await conn.close()
        except Exception:  # noqa: BLE001
            pass
        globals()[name] = None


def is_persistent() -> bool:
    """当前是否用 Postgres 后端（供外部诊断）。"""
    return _using_postgres


def get_store():
    """访问器：每次现取最新的 store 实例。

    不要在模块级 `from agents.runtime import store` 直接拿实例 —— 那样只会
    拿到 init_runtime 之前的初值（None）。用这个函数每次现读全局，保证
    init 之后的实例都能被下游看到。
    """
    if store is None:
        raise RuntimeError(
            "runtime store not initialized. "
            "Ensure FastAPI lifespan called init_runtime() before use."
        )
    return store


def get_checkpointer():
    """访问器：每次现取最新的 checkpointer 实例。同上。"""
    if checkpointer is None:
        raise RuntimeError(
            "runtime checkpointer not initialized. "
            "Ensure FastAPI lifespan called init_runtime() before use."
        )
    return checkpointer
