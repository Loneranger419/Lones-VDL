from __future__ import annotations

import pytest
from sqlalchemy import select

from lones_vdl import cookie_jar
from lones_vdl.config import Settings
from lones_vdl.db import create_db_engine, make_sessionmaker, upgrade, utcnow
from lones_vdl.db.models import Account, AccountRole, AuthTier
from lones_vdl.schemas import CookieHealth
from lones_vdl.services import accounts as account_service
from lones_vdl.services import cookies as cookie_service
from lones_vdl.services import settings_store

COOKIES = (
    "# Netscape HTTP Cookie File\n"
    "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t4102444800\tSID\tsecret-value\n"
    ".paypal.com\tTRUE\t/\tTRUE\t4102444800\tx\ty\n"
)


def write_legacy_jar(settings: Settings) -> None:
    cookies, _ = cookie_jar.filter_cookies(COOKIES, ["youtube"])
    cookie_jar.write_private(settings.cookies_file, cookie_jar.serialize(cookies))


@pytest.fixture
def db(settings: Settings):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = create_db_engine(settings.database_path)
    upgrade(engine)
    with make_sessionmaker(engine)() as session:
        yield session
        session.rollback()
    engine.dispose()


def test_create_validates_label_and_role(db):
    account_service.create(db, "Alt", AccountRole.ALTERNATE)
    with pytest.raises(account_service.AccountError):
        account_service.create(db, "Alt", AccountRole.PERSONAL)
    with pytest.raises(account_service.AccountError):
        account_service.create(db, "  ", AccountRole.PERSONAL)
    with pytest.raises(account_service.AccountError):
        account_service.create(db, "Other", "admin")


def test_import_keeps_only_youtube_and_never_reports_values(db, settings):
    account = account_service.create(db, "Alt", AccountRole.ALTERNATE)
    summary = account_service.import_cookies(settings, account, COOKIES)
    assert summary.kept == 1 and summary.dropped_domain == 1

    path = account_service.cookie_path(settings, account)
    assert path.parent == settings.accounts_dir
    assert "paypal" not in path.read_text()

    status = account_service.status(settings, account)
    assert status.present and status.cookie_count == 1
    assert status.health is not None and status.health.status == cookie_service.UNTESTED
    assert "secret-value" not in status.model_dump_json()


def test_import_rejects_files_without_login_cookies(db, settings):
    account = account_service.create(db, "Alt", AccountRole.ALTERNATE)
    text = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t4102444800\tPREF\tx\n"
    with pytest.raises(cookie_service.CookieImportError):
        account_service.import_cookies(settings, account, text)
    assert not account_service.has_cookies(settings, account)


def test_account_for_tier_matches_role_and_needs_cookies(db, settings):
    alt = account_service.create(db, "Alt", AccountRole.ALTERNATE)
    personal = account_service.create(db, "Me", AccountRole.PERSONAL)
    assert account_service.account_for_tier(settings, db, AuthTier.ANONYMOUS) is None
    assert account_service.account_for_tier(settings, db, AuthTier.ALTERNATE) is None

    account_service.import_cookies(settings, alt, COOKIES)
    account_service.import_cookies(settings, personal, COOKIES)
    assert account_service.account_for_tier(settings, db, AuthTier.ALTERNATE) == alt
    assert account_service.account_for_tier(settings, db, AuthTier.PERSONAL) == personal

    alt.enabled = False
    assert account_service.account_for_tier(settings, db, AuthTier.ALTERNATE) is None


def test_remove_deletes_the_cookie_file(db, settings):
    account = account_service.create(db, "Alt", AccountRole.ALTERNATE)
    account_service.import_cookies(settings, account, COOKIES)
    path = account_service.cookie_path(settings, account)
    account_service.remove(settings, db, account)
    db.flush()
    assert not path.exists()
    assert db.scalars(select(Account)).first() is None


def test_legacy_cookie_jar_becomes_the_alternate_account(db, settings):
    write_legacy_jar(settings)
    settings_store.put(
        db,
        cookie_service.HEALTH_KEY,
        CookieHealth(
            status=cookie_service.OK, checked_at=utcnow(), detail="fine"
        ).model_dump_json(),
    )
    account = account_service.adopt_legacy_cookies(settings, db)

    assert account is not None
    assert account.label == "Alternate" and account.role == AccountRole.ALTERNATE
    assert not settings.cookies_file.exists()
    assert account_service.has_cookies(settings, account)
    assert account.health_status == cookie_service.OK
    assert settings_store.get(db, cookie_service.HEALTH_KEY) == ""
    # Only once: with an account present, nothing else is adopted.
    write_legacy_jar(settings)
    assert account_service.adopt_legacy_cookies(settings, db) is None
