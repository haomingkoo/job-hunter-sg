"""Durable LangGraph checkpoint selection and lifecycle.

Production follows the application's PostgreSQL database automatically. Local
SQLite keeps using an isolated file, which is convenient for development and
tests without pretending that a container-local file survives deployment.
"""

from __future__ import annotations

import atexit
import sqlite3
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import config
from database import DATABASE_URL

from ..conversation_model import ConversationReply, PreferenceUpdatePayload


def _serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        allowed_msgpack_modules=(ConversationReply, PreferenceUpdatePayload),
    )


def _psycopg_url(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql://", 1)
    if database_url.startswith("postgresql+"):
        return "postgresql://" + database_url.split("://", 1)[1]
    return database_url


def build_checkpoint_store(
    database_url: str,
    sqlite_path: str,
) -> tuple[Any, Callable[[], None]]:
    """Build and initialize the checkpoint store for this process."""
    if database_url.startswith(("postgres://", "postgresql://", "postgresql+")):
        pool = ConnectionPool(
            conninfo=_psycopg_url(database_url),
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            min_size=1,
            max_size=config.DATABASE_POOL_SIZE,
            open=False,
        )
        pool.open(wait=True)
        saver = PostgresSaver(pool, serde=_serializer())
        try:
            saver.setup()
        except Exception:
            pool.close()
            raise
        return saver, pool.close

    connection = sqlite3.connect(sqlite_path, check_same_thread=False)
    saver = SqliteSaver(connection, serde=_serializer())
    try:
        saver.setup()
    except Exception:
        connection.close()
        raise
    return saver, connection.close


CHECKPOINTER, _close_checkpointer = build_checkpoint_store(
    DATABASE_URL,
    config.OPEN_AGENT_CHECKPOINT_DB_PATH,
)
atexit.register(_close_checkpointer)


def delete_checkpoint(thread_id: str) -> None:
    """Delete one durable LangGraph thread by its persisted identifier."""
    CHECKPOINTER.delete_thread(thread_id)
