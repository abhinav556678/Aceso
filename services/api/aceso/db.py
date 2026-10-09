import json
import time
import weakref
from contextlib import contextmanager
from typing import Optional

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import JsonbDumper, set_json_dumps
from psycopg_pool import ConnectionPool

from aceso.config import settings

# dicts go to jsonb columns as-is; UUID/Decimal/datetime inside them are stringified.
set_json_dumps(lambda obj: json.dumps(obj, default=str))
psycopg.adapters.register_dumper(dict, JsonbDumper)

SYSTEM_ACTOR = "system:pipeline"

_pool: Optional[ConnectionPool] = None


IDLE_CHECK_SECONDS = 20
_last_used: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _check_if_idle(conn) -> None:
    """Test a connection before handing it out, but only after it has sat idle.

    A connection that died with the network (Wi-Fi or VPN change) is then replaced
    instead of failing the request. Testing every time would cost a round trip to
    the database on each request, which is slow on a distant server.
    """
    now = time.monotonic()
    if now - _last_used.get(conn, 0.0) > IDLE_CHECK_SECONDS:
        ConnectionPool.check_connection(conn)
    _last_used[conn] = now


def open_pool(url: Optional[str] = None) -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            url or settings.database_url(),
            min_size=1,
            max_size=6,
            open=False,
            check=_check_if_idle,
            # prepare_threshold=None keeps us compatible with Supabase's pooler.
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
        )
        _pool.open(wait=True, timeout=20)
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


@contextmanager
def tx(user: Optional[dict] = None, actor: str = SYSTEM_ACTOR):
    """One transaction with the acting identity set for the audit/lifecycle triggers.

    `user` is a profiles row: auth.uid() resolves to it, so the DB enforces
    "only a doctor can confirm" and audit rows name the person. Without a user
    the transaction acts as the pipeline (auth.uid() is null).
    """
    sub = str(user["id"]) if user else ""
    claims = json.dumps({"sub": sub, "role": "authenticated"}) if user else ""
    with open_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select set_config('app.actor', %s, true), "
                "set_config('request.jwt.claim.sub', %s, true), "
                "set_config('request.jwt.claims', %s, true)",
                (user["full_name"] if user else actor, sub, claims),
            )
            yield cur


def audit(cur, action: str, entity_type: str, entity_id=None, patient_id=None,
          payload: Optional[dict] = None, user: Optional[dict] = None,
          from_state: Optional[str] = None, to_state: Optional[str] = None) -> None:
    cur.execute(
        """insert into audit_log(actor_id, actor_label, actor_role, action, entity_type,
                                 entity_id, patient_id, from_state, to_state, payload)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (user["id"] if user else None, user["full_name"] if user else SYSTEM_ACTOR,
         user["role"] if user else None, action, entity_type, entity_id, patient_id,
         from_state, to_state, payload or {}),
    )
