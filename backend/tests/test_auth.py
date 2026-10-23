from __future__ import annotations

import sqlite3

from conftest import PASSWORD

from lones_vdl.services.auth import SESSION_COOKIE, LoginThrottle


def test_first_run_setup(client):
    assert client.get("/api/auth/status").json() == {
        "setup_required": True,
        "authenticated": False,
    }
    assert client.post("/api/auth/setup", json={"password": "short"}).status_code == 422
    response = client.post("/api/auth/setup", json={"password": PASSWORD})
    assert response.status_code == 204
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    assert client.get("/api/auth/status").json() == {
        "setup_required": False,
        "authenticated": True,
    }
    assert client.post("/api/auth/setup", json={"password": PASSWORD}).status_code == 409


def test_api_requires_session(client):
    client.post("/api/auth/setup", json={"password": PASSWORD})
    client.cookies.clear()
    for path in ("/api/jobs", "/api/videos", "/api/system/ytdlp", "/api/events"):
        assert client.get(path).status_code == 401, path
    assert client.get("/api/health").status_code == 200


def test_login_logout(authed):
    authed.post("/api/auth/logout")
    assert authed.get("/api/jobs").status_code == 401
    assert authed.post("/api/auth/login", json={"password": "nope nope"}).status_code == 401
    assert authed.post("/api/auth/login", json={"password": PASSWORD}).status_code == 204
    assert authed.get("/api/jobs").status_code == 200


def test_remember_controls_cookie_lifetime(authed):
    authed.post("/api/auth/logout")
    remembered = authed.post("/api/auth/login", json={"password": PASSWORD, "remember": True})
    assert "max-age" in remembered.headers["set-cookie"].lower()
    session_only = authed.post("/api/auth/login", json={"password": PASSWORD, "remember": False})
    assert "max-age" not in session_only.headers["set-cookie"].lower()


def test_login_throttled_after_repeated_failures(authed):
    authed.post("/api/auth/logout")
    codes = [
        authed.post("/api/auth/login", json={"password": "wrong pass"}).status_code
        for _ in range(6)
    ]
    assert codes[:5] == [401] * 5  # five free attempts
    assert codes[5] == 429
    # even the right password is refused while locked out
    locked = authed.post("/api/auth/login", json={"password": PASSWORD})
    assert locked.status_code == 429
    assert "retry-after" in locked.headers


def test_csrf_header_required_for_writes(authed):
    response = authed.post(
        "/api/jobs", json={"url": "https://youtu.be/okokokokok1"}, headers={"x-lones-vdl": ""}
    )
    assert response.status_code == 403


def test_session_token_not_stored_in_plaintext(authed, settings):
    token = authed.cookies.get(SESSION_COOKIE)
    assert token
    with sqlite3.connect(settings.database_path) as db:
        stored = [row[0] for row in db.execute("SELECT token_hash FROM sessions")]
        password_hash = db.execute(
            "SELECT value FROM app_settings WHERE key='auth.password_hash'"
        ).fetchone()[0]
    assert token not in stored
    assert password_hash.startswith("$argon2")


def test_throttle_backoff_grows_and_resets():
    throttle = LoginThrottle(free_attempts=2, base_lock=10, max_lock=40)
    throttle.failure("ip")
    assert throttle.retry_after("ip") is None
    throttle.failure("ip")
    first = throttle.retry_after("ip")
    throttle.failure("ip")
    second = throttle.retry_after("ip")
    assert first is not None and second is not None and second > first
    throttle.success("ip")
    assert throttle.retry_after("ip") is None


def test_change_password_keeps_this_device_signed_in(authed):
    wrong = authed.post(
        "/api/auth/password", json={"current_password": "nope", "new_password": "another pass"}
    )
    assert wrong.status_code == 403
    short = authed.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "short"}
    )
    assert short.status_code == 422
    ok = authed.post(
        "/api/auth/password", json={"current_password": PASSWORD, "new_password": "another pass"}
    )
    assert ok.status_code == 204
    assert authed.get("/api/auth/status").json()["authenticated"] is True
    authed.post("/api/auth/logout")
    assert authed.post("/api/auth/login", json={"password": PASSWORD}).status_code == 401
    assert authed.post("/api/auth/login", json={"password": "another pass"}).status_code == 204
