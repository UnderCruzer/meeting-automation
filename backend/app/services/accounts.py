"""Per-user accounts and server-side sessions, stored next to the workspace in SQLite.

Passwords: scrypt (salted). Session tokens: random, only their SHA-256 is stored, so a
leaked database does not yield usable sessions. Disabling a user revokes their sessions.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

MIN_PASSWORD_LENGTH = 10
ROLES = ("admin", "member")
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}
_USERNAME_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789._-")


class AccountError(ValueError):
    """A request that violates an account rule (shown to the user)."""


@dataclass
class User:
    id: int
    username: str
    role: str
    active: bool
    must_change_password: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def public(self) -> dict:
        return {"id": self.id, "username": self.username, "role": self.role,
                "active": self.active, "mustChangePassword": self.must_change_password}


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt_b64, digest_b64 = stored.split("$")
        salt, expected = base64.b64decode(salt_b64), base64.b64decode(digest_b64)
    except ValueError:
        return False
    actual = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return hmac.compare_digest(actual, expected)


# Verified against unknown usernames so login timing does not reveal which users exist.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _validate_username(username: str) -> str:
    name = username.strip().lower()
    if not 3 <= len(name) <= 32 or not set(name) <= _USERNAME_CHARS:
        raise AccountError("사용자 이름은 3~32자의 영문 소문자, 숫자, . _ - 만 사용할 수 있습니다.")
    return name


def _validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AccountError(f"비밀번호는 {MIN_PASSWORD_LENGTH}자 이상이어야 합니다.")


class Accounts:
    def __init__(self, base_dir, session_hours: int = 12):
        self.path = Path(base_dir) / "workspace.sqlite3"
        self.session_hours = session_hours
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,"
                " password_hash TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,"
                " must_change INTEGER NOT NULL DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,"
                " expires_at TEXT NOT NULL)"
            )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def _user(row) -> User:
        return User(row["id"], row["username"], row["role"], bool(row["active"]), bool(row["must_change"]))

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def create(self, username: str, password: str, role: str = "member", must_change: bool = True) -> User:
        name = _validate_username(username)
        _validate_password(password)
        if role not in ROLES:
            raise AccountError("역할은 admin 또는 member 입니다.")
        try:
            with self.connect() as db:
                cur = db.execute(
                    "INSERT INTO users(username,password_hash,role,must_change) VALUES (?,?,?,?)",
                    (name, hash_password(password), role, int(must_change)),
                )
                row = db.execute("SELECT * FROM users WHERE id=?", (cur.lastrowid,)).fetchone()
        except sqlite3.IntegrityError:
            raise AccountError("이미 있는 사용자 이름입니다.")
        return self._user(row)

    def ensure_admin(self, username: str, password: str) -> User | None:
        """Create the first admin when no users exist yet (bootstrap from env)."""
        if self.count():
            return None
        return self.create(username, password, role="admin", must_change=False)

    def authenticate(self, username: str, password: str) -> User | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE username=?", (username.strip().lower(),)).fetchone()
        if row is None:
            verify_password(password, _DUMMY_HASH)
            return None
        if not verify_password(password, row["password_hash"]) or not row["active"]:
            return None
        return self._user(row)

    def start_session(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        expires = datetime.now(timezone.utc) + timedelta(hours=self.session_hours)
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(timezone.utc).isoformat(),))
            db.execute("INSERT INTO sessions VALUES (?,?,?)", (_token_hash(token), user.id, expires.isoformat()))
        return token

    def session_user(self, token: str) -> User | None:
        if not token:
            return None
        with self.connect() as db:
            row = db.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token_hash=? AND s.expires_at > ? AND u.active=1",
                (_token_hash(token), datetime.now(timezone.utc).isoformat()),
            ).fetchone()
        return self._user(row) if row else None

    def end_session(self, token: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))

    def change_password(self, user: User, current: str, new: str, keep_token: str) -> None:
        with self.connect() as db:
            row = db.execute("SELECT password_hash FROM users WHERE id=?", (user.id,)).fetchone()
        if row is None or not verify_password(current, row["password_hash"]):
            raise AccountError("현재 비밀번호가 맞지 않습니다.")
        _validate_password(new)
        with self.connect() as db:
            db.execute("UPDATE users SET password_hash=?, must_change=0 WHERE id=?", (hash_password(new), user.id))
            # Sign out other devices; keep the session that made the change.
            db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash!=?", (user.id, _token_hash(keep_token)))

    def list(self) -> list[User]:
        with self.connect() as db:
            return [self._user(r) for r in db.execute("SELECT * FROM users ORDER BY username").fetchall()]

    def update(self, actor: User, user_id: int, *, active: bool | None = None,
               role: str | None = None, password: str | None = None) -> User:
        with self.connect() as db:
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if row is None:
                raise AccountError("사용자를 찾을 수 없습니다.")
            target = self._user(row)
            if role is not None and role not in ROLES:
                raise AccountError("역할은 admin 또는 member 입니다.")
            losing_admin = target.is_admin and target.active and (active is False or role == "member")
            if losing_admin:
                if target.id == actor.id:
                    raise AccountError("자신의 관리자 권한이나 계정은 해제할 수 없습니다.")
                admins = db.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1").fetchone()[0]
                if admins <= 1:
                    raise AccountError("마지막 관리자는 해제할 수 없습니다.")
            if password is not None:
                _validate_password(password)
                db.execute("UPDATE users SET password_hash=?, must_change=1 WHERE id=?", (hash_password(password), user_id))
            if role is not None:
                db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
            if active is not None:
                db.execute("UPDATE users SET active=? WHERE id=?", (int(active), user_id))
            if active is False or password is not None:
                db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
            row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return self._user(row)
