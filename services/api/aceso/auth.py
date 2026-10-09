"""Sign-in for the three demo accounts.

One account per role (doctor, nurse, admin). The password for each comes from
.env; an account with no password set cannot sign in. A successful sign-in sets
a signed, HTTP-only session cookie, and every request acts as that role's seeded
profile, so the role checks here and the database's lifecycle triggers apply to it.

This is deliberately small: fixed accounts, no password reset, no lockout.
Replace it with Supabase JWT verification before any real use.
"""
import hashlib
import hmac
import secrets
import time
from typing import Optional

from fastapi import Cookie, Depends, Header, HTTPException, Query

from aceso.config import settings
from aceso.db import tx

ROLES = ("doctor", "nurse", "admin")
SESSION_COOKIE = "aceso_session"
SESSION_SECONDS = 12 * 3600
# without SESSION_SECRET in .env, sessions end when the API restarts
_SECRET = (settings.session_secret or secrets.token_hex(32)).encode()


def _sign(payload: str) -> str:
    return hmac.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def issue_session(role: str) -> str:
    payload = f"{role}.{int(time.time()) + SESSION_SECONDS}"
    return f"{payload}.{_sign(payload)}"


def read_session(token: Optional[str]) -> Optional[str]:
    """The role a session cookie stands for, or None if it is missing, forged or expired."""
    role, _, rest = (token or "").partition(".")
    expires, _, signature = rest.partition(".")
    if role not in ROLES or not expires.isdigit() or not hmac.compare_digest(signature, _sign(f"{role}.{expires}")):
        return None
    return role if int(expires) > time.time() else None


def check_password(username: str, password: str) -> Optional[str]:
    """The role for these credentials, or None. The username is the role name."""
    role = username.strip().lower()
    expected = {"doctor": settings.doctor_password, "nurse": settings.nurse_password,
                "admin": settings.admin_password}.get(role, "")
    # compare even for an unknown user, so a wrong username takes as long as a wrong password
    matches = hmac.compare_digest(password.encode(), (expected or secrets.token_hex(8)).encode())
    return role if expected and matches else None


def profile_for(role: str) -> dict:
    with tx() as cur:
        cur.execute(
            "select id, full_name, role::text as role, registration_no from profiles "
            "where role = %s::user_role order by created_at limit 1", (role,))
        user = cur.fetchone()
    if not user:
        raise HTTPException(401, f"No seeded {role} profile. Run scripts/setup_db.py.")
    return user


def current_user(
    session: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
    x_demo_role: Optional[str] = Header(default=None),
    as_role: Optional[str] = Query(default=None, alias="as"),
) -> dict:
    role = read_session(session)
    if settings.demo_role_header and (x_demo_role or as_role):
        # tests and scripts name the role directly; off unless DEMO_ROLE_HEADER is set
        role = (x_demo_role or as_role or "").lower()
    if role not in ROLES:
        raise HTTPException(401, "Sign in to continue.")
    return profile_for(role)


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
