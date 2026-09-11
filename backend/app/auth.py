"""
backend/app/auth.py

Authentication and role gating for the operator-facing endpoints.

Why this exists
---------------
The review gate (ai/updates) is the mechanism that decides what enters the
corpus, and the corpus is what every answer is grounded in. Before this
module, `POST /updates/{id}/approve` took the reviewer's name as a plain
string in the request body and wrote it into the audit trail unverified.
That is not an audit trail; it is a text field. Anyone who could reach the
API could approve a regulatory update and sign it "Registrar of Patents".

So the identity recorded against a decision now comes from a verified
token and never from the request body. `ReviewDecisionRequest` no longer
carries `decided_by` at all — the field was removed rather than ignored,
because a field the server silently overrides is a trap for the next
person who reads the schema.

Roles
-----
    USER      — the public product surface. Ask, assess, browse sources.
                No token is required for any of that, and none is issued
                for it: an anonymous visitor is a USER by default.
    REVIEWER  — may approve/reject/clear-audit queued corpus updates.
    ADMIN     — everything a REVIEWER may do, plus publishing (running the
                real ingestion pipeline) and forcing a source check.

Roles are ordered, so `require_role("REVIEWER")` admits an ADMIN too.

Credentials
-----------
Accounts come from the IPSAKTI_USERS environment variable, as
`name:role:bcrypt-hash` triples separated by commas or newlines. There is
no user-registration flow and no user database: this is a small operator
console with a handful of named reviewers, and inventing a signup system
for it would add an attack surface with no user behind it.

When IPSAKTI_USERS is unset, a development account pair is generated with
random passwords that are logged once at startup. That keeps a fresh clone
runnable without shipping a known-password backdoor — a hardcoded default
credential is the single most common way a demo deployment becomes a real
incident.

The signing secret works the same way: IPSAKTI_JWT_SECRET if set, else a
random one per process. A random per-process secret means tokens do not
survive a restart, which is correct for a deployment that never configured
one — the alternative is a predictable secret, and a predictable secret is
the same as no signature at all.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import secrets
from dataclasses import dataclass
from typing import Annotated, Any

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

log = logging.getLogger(__name__)

ALGORITHM = "HS256"
TOKEN_TTL_MINUTES = 12 * 60

# Ordered weakest-first: a role admits every role at or below its index.
ROLES = ("USER", "REVIEWER", "ADMIN")

# bcrypt has a hard 72-byte input limit and raises on longer input.
# Truncating silently would mean two different passwords authenticating the
# same account, so long input is rejected instead.
MAX_PASSWORD_BYTES = 72

# RFC 7518 3.2: an HMAC key shorter than the hash output weakens the
# signature. Anything shorter than this is refused rather than accepted
# with a warning, because a secret nobody notices is too short is exactly
# the one that stays too short.
MIN_SECRET_BYTES = 32

# The cost of a bcrypt hash that is never going to match, used to keep a
# failed login for an unknown user as slow as one for a known user. Built
# once: doing it per request would double the work of every failed login.
_DUMMY_HASH = bcrypt.hashpw(b"no-such-account", bcrypt.gensalt())

# tokenUrl is what OpenAPI's "Authorize" button posts to. auto_error is off
# so an anonymous request reaches the endpoint and gets our own 401 with a
# usable message, rather than FastAPI's bare one.
_bearer = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


@dataclass(frozen=True)
class Account:
    username: str
    role: str
    password_hash: str


@dataclass(frozen=True)
class Identity:
    """The verified caller. This — not the request body — is what gets
    written into the audit trail as `decided_by`."""
    username: str
    role: str

    def at_least(self, role: str) -> bool:
        return ROLES.index(self.role) >= ROLES.index(role)


def hash_password(password: str) -> str:
    _check_password_length(password)
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _check_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError(
            f"password exceeds bcrypt's {MAX_PASSWORD_BYTES}-byte limit"
        )


def _verify_password(password: str, hashed: str) -> bool:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:  # a malformed hash in config must not 500 the login
        log.exception("password verification failed for a stored hash")
        return False


def _parse_accounts(raw: str) -> dict[str, Account]:
    """Parse IPSAKTI_USERS: `name:role:bcrypt-hash`, comma/newline separated.

    A bcrypt hash contains `$` and `/` but never `:`, so splitting on the
    first two colons is unambiguous.
    """
    accounts: dict[str, Account] = {}
    for entry in raw.replace("\n", ",").split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":", 2)
        if len(parts) != 3:
            log.error("ignoring malformed IPSAKTI_USERS entry (expected name:role:hash)")
            continue
        username, role, password_hash = (p.strip() for p in parts)
        role = role.upper()
        if role not in ROLES:
            log.error("ignoring account %r: unknown role %r", username, role)
            continue
        if not username or not password_hash:
            log.error("ignoring IPSAKTI_USERS entry with an empty name or hash")
            continue
        accounts[username] = Account(username, role, password_hash)
    return accounts


def _dev_accounts() -> dict[str, Account]:
    """Random-password reviewer/admin accounts for an unconfigured clone.

    Logged once, at WARNING, so the passwords are visible to whoever
    started the process and to nobody else. Regenerated every restart:
    these are for a developer running ./scripts/run.sh, not for a
    deployment, and a deployment is expected to set IPSAKTI_USERS.
    """
    made = {}
    for username, role in (("reviewer", "REVIEWER"), ("admin", "ADMIN")):
        password = secrets.token_urlsafe(12)
        made[username] = Account(username, role, hash_password(password))
        log.warning(
            "IPSAKTI_USERS is not set — generated a temporary %s account: "
            "username=%s password=%s (valid until this process restarts)",
            role, username, password,
        )
    return made


class AuthService:
    def __init__(self) -> None:
        self._accounts: dict[str, Account] | None = None
        self._secret: str | None = None

    @property
    def accounts(self) -> dict[str, Account]:
        # Read lazily rather than at import: the tests set IPSAKTI_USERS
        # per case, and a module-level read would freeze whatever the
        # environment happened to be when the first import ran.
        if self._accounts is None:
            raw = os.environ.get("IPSAKTI_USERS", "").strip()
            self._accounts = _parse_accounts(raw) if raw else _dev_accounts()
        return self._accounts

    @property
    def secret(self) -> str:
        if self._secret is None:
            configured = os.environ.get("IPSAKTI_JWT_SECRET", "")
            if configured and len(configured.encode("utf-8")) < MIN_SECRET_BYTES:
                # Refuse rather than fall back to a random one: a process
                # that quietly ignored the configured secret would issue
                # tokens no other replica could verify, which looks like
                # random logouts rather than like a misconfiguration.
                raise RuntimeError(
                    f"IPSAKTI_JWT_SECRET must be at least {MIN_SECRET_BYTES} bytes"
                )
            self._secret = configured or secrets.token_urlsafe(48)
        return self._secret

    def reset(self) -> None:
        """Drop cached accounts and secret. For tests that change the env."""
        self._accounts = None
        self._secret = None

    def authenticate(self, username: str, password: str) -> Identity | None:
        account = self.accounts.get(username)
        if account is None:
            # Check against a throwaway hash anyway, so a missing username
            # and a wrong password take the same time — otherwise the
            # response time enumerates valid account names.
            bcrypt.checkpw(
                password.encode("utf-8")[:MAX_PASSWORD_BYTES], _DUMMY_HASH
            )
            return None
        if not _verify_password(password, account.password_hash):
            return None
        return Identity(account.username, account.role)

    def issue_token(self, identity: Identity) -> tuple[str, int]:
        expires = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=TOKEN_TTL_MINUTES)
        payload: dict[str, Any] = {
            "sub": identity.username,
            "role": identity.role,
            "exp": expires,
        }
        return jwt.encode(payload, self.secret, algorithm=ALGORITHM), TOKEN_TTL_MINUTES * 60

    def decode(self, token: str) -> Identity | None:
        try:
            # algorithms is a whitelist, not a hint: without it a token
            # carrying alg:none — or an asymmetric alg verified against the
            # public key as an HMAC secret — would be accepted as valid.
            payload = jwt.decode(token, self.secret, algorithms=[ALGORITHM])
        except jwt.InvalidTokenError:
            return None
        username = payload.get("sub")
        role = payload.get("role")
        if not username or role not in ROLES:
            return None
        # A token is a claim about an account, not a substitute for it: an
        # account removed from IPSAKTI_USERS must stop being able to
        # approve things before its last token expires.
        account = self.accounts.get(username)
        if account is None or account.role != role:
            return None
        return Identity(username, role)


auth_service = AuthService()


def current_identity(
    token: Annotated[str | None, Depends(_bearer)],
) -> Identity | None:
    """The caller, or None for an anonymous request. Never raises — the
    public endpoints are anonymous by design, so 'no token' is a normal
    state, not an error."""
    if not token:
        return None
    return auth_service.decode(token)


def require_role(role: str):
    """Dependency factory: admit callers at `role` or above.

    Returns the Identity, so the endpoint writes the verified username into
    the audit trail without a second lookup.
    """
    if role not in ROLES:  # a typo here would silently admit everyone
        raise ValueError(f"unknown role {role!r}")

    def dependency(
        identity: Annotated[Identity | None, Depends(current_identity)],
    ) -> Identity:
        if identity is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sign in to perform this action.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not identity.at_least(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the {role} role.",
            )
        return identity

    return dependency
