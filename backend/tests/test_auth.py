"""Authentication and role gating.

The point of these tests is not that login works — it is that the review
gate cannot be operated without it. Every assertion below is about an
action that changes what enters the corpus being refused to a caller who
has not proved who they are.
"""

from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import Identity, auth_service, hash_password  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@pytest.fixture
def accounts(monkeypatch):
    """A known account set, replacing whatever the environment configured."""
    monkeypatch.setenv(
        "IPSAKTI_USERS",
        f"rev:REVIEWER:{hash_password('rev-pass')},"
        f"boss:ADMIN:{hash_password('boss-pass')},"
        f"plain:USER:{hash_password('plain-pass')}",
    )
    monkeypatch.setenv("IPSAKTI_JWT_SECRET", "test-secret-not-for-deployment-0123456789")
    auth_service.reset()
    yield
    auth_service.reset()


def login(username: str, password: str):
    return client.post(
        "/api/v1/auth/login", data={"username": username, "password": password}
    )


def bearer(username: str, password: str) -> dict[str, str]:
    res = login(username, password)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_returns_token_and_role(accounts):
    res = login("rev", "rev-pass")
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["username"] == "rev"
    assert body["role"] == "REVIEWER"
    assert body["access_token"]


def test_login_with_wrong_password_is_rejected(accounts):
    assert login("rev", "not-the-password").status_code == 401


def test_unknown_user_and_wrong_password_are_indistinguishable(accounts):
    """Different messages here would let an attacker enumerate accounts."""
    missing = login("nobody", "whatever")
    wrong = login("rev", "whatever")
    assert missing.status_code == wrong.status_code == 401
    assert missing.json()["detail"] == wrong.json()["detail"]


def test_me_reports_the_token_holder(accounts):
    res = client.get("/api/v1/auth/me", headers=bearer("boss", "boss-pass"))
    assert res.status_code == 200
    assert res.json() == {"username": "boss", "role": "ADMIN"}


def test_me_rejects_a_garbage_token(accounts):
    res = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert res.status_code == 401


def test_token_signed_with_another_secret_is_rejected(accounts, monkeypatch):
    """A token is only as good as the signature check behind it."""
    import jwt

    forged = jwt.encode(
        {"sub": "boss", "role": "ADMIN", "exp": 9999999999},
        "a-different-secret-of-more-than-32-bytes",
        algorithm="HS256",
    )
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert res.status_code == 401


def test_token_for_a_removed_account_stops_working(accounts, monkeypatch):
    """Revocation must not wait for the token to expire."""
    headers = bearer("rev", "rev-pass")
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200

    monkeypatch.setenv("IPSAKTI_USERS", f"boss:ADMIN:{hash_password('boss-pass')}")
    auth_service.reset()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_token_claiming_a_higher_role_than_the_account_is_rejected(accounts):
    """The role in the token is checked against the account, so a token
    minted for an escalated role does not outlive that check."""
    token, _ = auth_service.issue_token(Identity("rev", "ADMIN"))
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# The review gate
# ---------------------------------------------------------------------------

DECISION_ACTIONS = ["approve", "reject", "clear-audit"]


@pytest.mark.parametrize("action", DECISION_ACTIONS)
def test_review_decisions_reject_anonymous_callers(accounts, action):
    res = client.post(f"/api/v1/updates/e1/{action}", json={"notes": "n"})
    assert res.status_code == 401


@pytest.mark.parametrize("action", DECISION_ACTIONS)
def test_review_decisions_reject_plain_users(accounts, action):
    res = client.post(
        f"/api/v1/updates/e1/{action}",
        json={"notes": "n"},
        headers=bearer("plain", "plain-pass"),
    )
    assert res.status_code == 403


@pytest.mark.parametrize("action", DECISION_ACTIONS)
def test_admin_may_do_anything_a_reviewer_may(accounts, action, monkeypatch):
    """Roles are ordered — an ADMIN is not locked out of reviewer work."""
    from app.api import updates_routes

    seen = {}

    class FakeUpdatesService:
        def approve(self, entry_id, *, decided_by, notes=None):
            seen["by"] = decided_by

        reject = approve
        clear_audit = approve

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    res = client.post(
        f"/api/v1/updates/e1/{action}",
        json={"notes": "n"},
        headers=bearer("boss", "boss-pass"),
    )
    assert res.status_code == 200
    assert seen["by"] == "boss"


def test_decided_by_in_the_body_cannot_override_the_token(accounts, monkeypatch):
    """The whole reason this module exists: signing someone else's name to
    a decision must be impossible, not merely discouraged."""
    from app.api import updates_routes

    seen = {}

    class FakeUpdatesService:
        def approve(self, entry_id, *, decided_by, notes=None):
            seen["by"] = decided_by

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    res = client.post(
        "/api/v1/updates/e1/approve",
        json={"decided_by": "Registrar of Patents", "notes": "n"},
        headers=bearer("rev", "rev-pass"),
    )
    assert res.status_code == 200
    assert seen["by"] == "rev"


def test_publish_requires_admin_not_merely_reviewer(accounts):
    """Publishing runs the ingestion pipeline — it changes what every
    future answer is grounded in, so it sits a rung above approval."""
    res = client.post("/api/v1/updates/e1/publish", headers=bearer("rev", "rev-pass"))
    assert res.status_code == 403


def test_check_now_requires_admin(accounts):
    res = client.post(
        "/api/v1/updates/check-now", json={}, headers=bearer("rev", "rev-pass")
    )
    assert res.status_code == 403


def test_reading_the_queue_stays_open(accounts, monkeypatch):
    """Deciding is gated; inspecting what the system proposes to ingest is
    not. These are public regulatory documents, and hiding the queue would
    make the review gate less accountable, not more secure."""
    from app.api import updates_routes

    class FakeUpdatesService:
        def pending(self):
            return []

    monkeypatch.setattr(updates_routes, "updates_service", FakeUpdatesService())
    assert client.get("/api/v1/updates/pending").status_code == 200


# ---------------------------------------------------------------------------
# Password handling
# ---------------------------------------------------------------------------

def test_overlong_password_is_rejected_rather_than_truncated(accounts):
    """bcrypt ignores input past 72 bytes. Truncating silently would mean
    two different passwords opening the same account."""
    long_password = "rev-pass" + "x" * 200
    assert login("rev", long_password).status_code == 401


def test_malformed_account_entries_are_skipped_not_fatal(monkeypatch):
    monkeypatch.setenv(
        "IPSAKTI_USERS",
        f"broken-entry,ghost:NOT_A_ROLE:{hash_password('x')},"
        f"rev:REVIEWER:{hash_password('rev-pass')}",
    )
    monkeypatch.setenv("IPSAKTI_JWT_SECRET", "test-secret-not-for-deployment-0123456789")
    auth_service.reset()
    try:
        assert set(auth_service.accounts) == {"rev"}
        assert login("rev", "rev-pass").status_code == 200
    finally:
        auth_service.reset()
