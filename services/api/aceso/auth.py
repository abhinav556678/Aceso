"""Demo authentication.

The prototype has no password login: the web app sends the role picked on the
login screen and the API acts as the matching seeded profile. Role checks and
the database's lifecycle triggers still apply to that profile. Replace
`current_user` with Supabase JWT verification before any real use.
"""
from typing import Optional

from fastapi import Depends, Header, HTTPException, Query

from aceso.db import tx

ROLES = ("doctor", "nurse", "admin")


def current_user(
    x_demo_role: Optional[str] = Header(default=None),
    as_role: Optional[str] = Query(default=None, alias="as"),
) -> dict:
    role = (x_demo_role or as_role or "").lower()
    if role not in ROLES:
        raise HTTPException(401, "Pick a demo role on the login screen (doctor, nurse or admin).")
    with tx() as cur:
        cur.execute(
            "select id, full_name, role::text as role, registration_no from profiles "
            "where role = %s::user_role order by created_at limit 1", (role,))
        user = cur.fetchone()
    if not user:
        raise HTTPException(401, f"No seeded {role} profile. Run scripts/setup_db.py.")
    return user


def require_role(*roles: str):
    def dep(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(403, f"{user['role']} is not allowed to do this (needs: {', '.join(roles)}).")
        return user
    return dep


clinical = require_role("doctor", "nurse")
doctor_only = require_role("doctor")
admin_only = require_role("admin")
any_role = require_role(*ROLES)
