"""Sign in, sign out, and who is signed in."""
import time

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from aceso import auth
from aceso.db import audit, tx

router = APIRouter()


class Credentials(BaseModel):
    username: str = Field(max_length=60)
    password: str = Field(max_length=200)


@router.post("/login")
def login(body: Credentials, response: Response):
    role = auth.check_password(body.username, body.password)
    if not role:
        time.sleep(0.5)  # slows down guessing; every attempt is also in the audit log
        with tx() as cur:
            audit(cur, "auth.login_failed", "session", payload={"username": body.username.strip()[:60]})
        raise HTTPException(401, "The username or password is not correct.")
    user = auth.profile_for(role)
    with tx(user) as cur:
        audit(cur, "auth.login", "session", user=user)
    response.set_cookie(auth.SESSION_COOKIE, auth.issue_session(role), max_age=auth.SESSION_SECONDS,
                        httponly=True, samesite="lax", path="/")
    return {"name": user["full_name"], "role": user["role"]}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/session")
def session(user: dict = Depends(auth.any_role)):
    return {"name": user["full_name"], "role": user["role"]}
