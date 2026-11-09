"""Pule połączeń PostgreSQL.

Pula "portal" obsługuje schemat aplikacyjny. Dla warstw z projektów QGIS tworzona jest
osobna pula per unikalny conninfo (service / dbname z datasource warstwy), więc warstwy
mogą pochodzić z różnych baz, o ile są zdefiniowane w pg_service.conf.
"""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import get_settings

_pools: dict[str, AsyncConnectionPool] = {}


async def _get_pool(conninfo: str) -> AsyncConnectionPool:
    pool = _pools.get(conninfo)
    if pool is None:
        pool = AsyncConnectionPool(
            conninfo, min_size=1, max_size=10, open=False, kwargs={"row_factory": dict_row}
        )
        await pool.open()
        _pools[conninfo] = pool
    return pool


@asynccontextmanager
async def portal_conn() -> AsyncIterator[AsyncConnection]:
    pool = await _get_pool(f"service={get_settings().portal_db_service}")
    async with pool.connection() as conn:
        yield conn


@asynccontextmanager
async def layer_conn(conninfo: str) -> AsyncIterator[AsyncConnection]:
    pool = await _get_pool(conninfo)
    async with pool.connection() as conn:
        yield conn


async def close_pools() -> None:
    for pool in _pools.values():
        await pool.close()
    _pools.clear()
