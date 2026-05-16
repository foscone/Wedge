import hmac
import os
from typing import Optional

import bcrypt
from fastapi import HTTPException, Request, Response
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY or len(SECRET_KEY) < 16:
    raise RuntimeError("SECRET_KEY must be set to a strong random string of >= 16 chars")

ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
if not ADMIN_PASSWORD:
    raise RuntimeError("ADMIN_PASSWORD must be set in the environment")

SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30"))
SESSION_MAX_AGE = SESSION_DAYS * 86400
COOKIE_NAME = "wedge_session"

_serializer = URLSafeTimedSerializer(SECRET_KEY, salt="wedge-session")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except Exception:
        return False


def verify_admin_password(plain: str) -> bool:
    return hmac.compare_digest(
        plain.encode("utf-8"), ADMIN_PASSWORD.encode("utf-8")
    )


def load_session(request: Request) -> dict:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return {}
    try:
        data = _serializer.loads(raw, max_age=SESSION_MAX_AGE)
        if isinstance(data, dict):
            return data
    except (BadSignature, SignatureExpired):
        pass
    return {}


def save_session(response: Response, data: dict) -> None:
    token = _serializer.dumps(data)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def require_admin(request: Request) -> None:
    s = load_session(request)
    if not s.get("admin"):
        raise HTTPException(401, "admin login required")


def require_project_level(request: Request, slug: str, need: str) -> str:
    """need: 'view' or 'edit'. Returns the actual granted level."""
    s = load_session(request)
    projects = s.get("projects", {}) or {}
    have = projects.get(slug)
    if have not in ("view", "edit"):
        raise HTTPException(401, "project login required")
    if need == "edit" and have != "edit":
        raise HTTPException(403, "edit access required")
    return have


def grant_project_access(session: dict, slug: str, level: str) -> dict:
    projects = dict(session.get("projects", {}) or {})
    # 'edit' supersedes 'view'
    if projects.get(slug) == "edit" and level == "view":
        pass
    else:
        projects[slug] = level
    session["projects"] = projects
    return session


def revoke_project_access(session: dict, slug: str) -> dict:
    projects = dict(session.get("projects", {}) or {})
    projects.pop(slug, None)
    session["projects"] = projects
    return session
