"""Single-owner access gate for the hosted personal court; no model key reaches the browser."""
import hashlib
import hmac
import os
import time

from fastapi import Request

COOKIE = "ministers_access"
MAX_AGE = 86400
_attempts: dict[str, list[float]] = {}


def key() -> str:
    return os.environ.get("MINISTERS_ACCESS_KEY", "")


def issue() -> str:
    stamp = str(int(time.time()))
    signature = hmac.new(key().encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return stamp + "." + signature


def allowed(request: Request) -> bool:
    if not key():
        return not os.environ.get("RENDER")
    token = request.cookies.get(COOKIE, "")
    stamp, _, signature = token.partition(".")
    try:
        age = time.time() - int(stamp)
    except ValueError:
        return False
    expected = hmac.new(key().encode(), stamp.encode(), hashlib.sha256).hexdigest()
    return 0 <= age <= MAX_AGE and hmac.compare_digest(signature, expected)


def login_limited(request: Request) -> bool:
    # Bound failed login attempts per client without adding a cache dependency.
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [t for t in _attempts.get(client, []) if now - t < 300]
    if len(_attempts) > 4096:
        for ip in list(_attempts):
            if not _attempts[ip] or now - _attempts[ip][-1] >= 300:
                del _attempts[ip]
    _attempts[client] = recent
    if len(recent) >= 6:
        return True
    recent.append(now)
    return False
