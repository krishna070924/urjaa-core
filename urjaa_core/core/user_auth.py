import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import bcrypt
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from urjaa_core.core.database import engine, get_db
from urjaa_core.models.address import Address
from urjaa_core.models.base import Base
from urjaa_core.models.password_reset_token import PasswordResetToken
from urjaa_core.models.user import User
from urjaa_core.models.user_refresh_token import UserRefreshToken



DEFAULT_USER_ACCESS_JWT_TTL_SECONDS = 60 * 15
DEFAULT_USER_REFRESH_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 30
DEFAULT_PASSWORD_RESET_TOKEN_TTL_SECONDS = 60 * 15

USER_SOURCE_WEBSITE = "WEBSITE"
USER_SOURCE_STORE = "STORE"
USER_SOURCE_ADMIN = "ADMIN"
USER_SOURCE_VALUES = (
    USER_SOURCE_WEBSITE,
    USER_SOURCE_STORE,
    USER_SOURCE_ADMIN,
)


def _get_secret() -> str:
    secret = os.getenv("USER_JWT_SECRET")
    if not secret:
        raise ValueError("CRITICAL: USER_JWT_SECRET env var is not set.")
    return secret


def _get_positive_int_env(env_name: str, default_value: int) -> int:
    raw = (os.getenv(env_name) or "").strip()
    if not raw:
        return default_value

    try:
        value = int(raw)
    except ValueError:
        return default_value

    return value if value > 0 else default_value


def _get_access_ttl_seconds() -> int:
    return _get_positive_int_env("USER_ACCESS_JWT_TTL_SECONDS", DEFAULT_USER_ACCESS_JWT_TTL_SECONDS)


def _get_refresh_ttl_seconds() -> int:
    return _get_positive_int_env("USER_REFRESH_TOKEN_TTL_SECONDS", DEFAULT_USER_REFRESH_TOKEN_TTL_SECONDS)


def _get_password_reset_ttl_seconds() -> int:
    return _get_positive_int_env("PASSWORD_RESET_TOKEN_TTL_SECONDS", DEFAULT_PASSWORD_RESET_TOKEN_TTL_SECONDS)


def _utcnow() -> datetime:
    # Keep naive UTC timestamps to align with TIMESTAMP columns used in this project.
    return datetime.utcnow()


def _token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _sign(message: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _table_exists(connection, table_name: str) -> bool:
    exists = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name = :table_name
            )
            """
        ),
        {"table_name": table_name},
    ).scalar()
    return bool(exists)


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    exists = connection.execute(
        text(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = :table_name
                  AND column_name = :column_name
            )
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
        },
    ).scalar()
    return bool(exists)


def _column_udt_name(connection, table_name: str, column_name: str) -> str | None:
    return connection.execute(
        text(
            """
            SELECT udt_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
              AND column_name = :column_name
            """
        ),
        {
            "table_name": table_name,
            "column_name": column_name,
        },
    ).scalar()


def _lookup_user_id_by_email(connection, normalized_email: str) -> UUID | None:
    return connection.execute(
        text(
            """
            SELECT id
            FROM users
            WHERE lower(email) = :normalized_email
            LIMIT 1
            """
        ),
        {"normalized_email": normalized_email},
    ).scalar()


def _ensure_unique_store_customer_email(
    connection,
    preferred_email: str | None,
    legacy_customer_id: int,
) -> str:
    if preferred_email and "@" in preferred_email:
        local_part, domain_part = preferred_email.split("@", 1)
    else:
        local_part = f"store-customer-{legacy_customer_id}"
        domain_part = "store.local"

    local_part = (local_part or f"store-customer-{legacy_customer_id}").strip().lower() or f"store-customer-{legacy_customer_id}"
    domain_part = (domain_part or "store.local").strip().lower() or "store.local"

    suffix = 0
    while True:
        candidate_local = local_part if suffix == 0 else f"{local_part}+{suffix}"
        candidate = f"{candidate_local}@{domain_part}"
        exists = _lookup_user_id_by_email(connection, candidate)
        if exists is None:
            return candidate
        suffix += 1


def _migrate_legacy_sales_customers_to_users(connection) -> None:
    if not _table_exists(connection, "users"):
        return

    legacy_customer_id_to_user_id: dict[int, UUID] = {}
    placeholder_password_hash = hash_user_password(secrets.token_urlsafe(48))

    if _table_exists(connection, "customers"):
        legacy_customers = connection.execute(
            text(
                """
                SELECT
                    id,
                    name,
                    phone,
                    email,
                    address,
                    feedback,
                    is_deleted
                FROM customers
                ORDER BY id ASC
                """
            )
        ).mappings().all()

        for legacy_customer in legacy_customers:
            legacy_customer_id = int(legacy_customer["id"])
            full_name = (legacy_customer.get("name") or "").strip() or f"Store Customer {legacy_customer_id}"
            phone = (legacy_customer.get("phone") or "").strip() or None
            address = (legacy_customer.get("address") or "").strip() or None
            feedback = (legacy_customer.get("feedback") or "").strip() or None
            is_deleted = bool(legacy_customer.get("is_deleted") or False)

            email_raw = (legacy_customer.get("email") or "").strip().lower()
            normalized_email = email_raw if email_raw and "@" in email_raw else None

            existing_user_id: UUID | None = None
            if normalized_email:
                existing_user_id = _lookup_user_id_by_email(connection, normalized_email)

            if existing_user_id is not None:
                legacy_customer_id_to_user_id[legacy_customer_id] = existing_user_id
                connection.execute(
                    text(
                        """
                        UPDATE users
                        SET
                            full_name = CASE WHEN full_name IS NULL OR full_name = '' THEN :full_name ELSE full_name END,
                            phone = CASE WHEN phone IS NULL OR phone = '' THEN :phone ELSE phone END,
                            address = COALESCE(address, :address),
                            feedback = COALESCE(feedback, :feedback),
                            is_active = CASE WHEN :legacy_is_deleted THEN is_active ELSE TRUE END
                        WHERE id = :user_id
                        """
                    ),
                    {
                        "user_id": existing_user_id,
                        "full_name": full_name,
                        "phone": phone,
                        "address": address,
                        "feedback": feedback,
                        "legacy_is_deleted": is_deleted,
                    },
                )
                continue

            user_email = _ensure_unique_store_customer_email(connection, normalized_email, legacy_customer_id)
            created_user_id = connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id,
                        email,
                        password_hash,
                        full_name,
                        phone,
                        source,
                        address,
                        feedback,
                        provider,
                        provider_id,
                        is_active
                    )
                    VALUES (
                        :id,
                        :email,
                        :password_hash,
                        :full_name,
                        :phone,
                        :source,
                        :address,
                        :feedback,
                        'local',
                        NULL,
                        :is_active
                    )
                    RETURNING id
                    """
                ),
                {
                    "id": uuid4(),
                    "email": user_email,
                    "password_hash": placeholder_password_hash,
                    "full_name": full_name,
                    "phone": phone,
                    "source": USER_SOURCE_STORE,
                    "address": address,
                    "feedback": feedback,
                    "is_active": not is_deleted,
                },
            ).scalar_one()

            legacy_customer_id_to_user_id[legacy_customer_id] = created_user_id

    if not _table_exists(connection, "sales"):
        return

    sales_customer_id_udt = _column_udt_name(connection, "sales", "customer_id")
    if sales_customer_id_udt == "uuid":
        return

    if sales_customer_id_udt != "int4":
        return

    connection.execute(text("ALTER TABLE sales ADD COLUMN IF NOT EXISTS customer_user_id UUID"))

    for legacy_customer_id, user_id in legacy_customer_id_to_user_id.items():
        connection.execute(
            text(
                """
                UPDATE sales
                SET customer_user_id = :user_id
                WHERE customer_id = :legacy_customer_id
                """
            ),
            {
                "user_id": user_id,
                "legacy_customer_id": legacy_customer_id,
            },
        )

    fk_constraints = connection.execute(
        text(
            """
            SELECT conname
            FROM pg_constraint
            WHERE conrelid = 'sales'::regclass
              AND contype = 'f'
              AND pg_get_constraintdef(oid) ILIKE '%(customer_id)%'
            """
        )
    ).scalars().all()

    for constraint_name in fk_constraints:
        escaped_name = str(constraint_name).replace('"', '""')
        connection.execute(text(f'ALTER TABLE sales DROP CONSTRAINT IF EXISTS "{escaped_name}"'))

    connection.execute(text("DROP INDEX IF EXISTS idx_sales_customer_id"))
    connection.execute(text("ALTER TABLE sales DROP COLUMN IF EXISTS customer_id"))

    if _column_exists(connection, "sales", "customer_user_id") and not _column_exists(connection, "sales", "customer_id"):
        connection.execute(text("ALTER TABLE sales RENAME COLUMN customer_user_id TO customer_id"))

    connection.execute(
        text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'sales_customer_id_fkey'
                ) THEN
                    ALTER TABLE sales
                    ADD CONSTRAINT sales_customer_id_fkey
                    FOREIGN KEY (customer_id) REFERENCES users(id);
                END IF;
            END
            $$;
            """
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS idx_sales_customer_id ON sales(customer_id)"))


def ensure_user_auth_schema() -> None:
    Base.metadata.create_all(
        bind=engine,
        tables=[
            User.__table__,
            Address.__table__,
            UserRefreshToken.__table__,
            PasswordResetToken.__table__,
        ],
    )

    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS provider VARCHAR(32)"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS provider_id VARCHAR(255)"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS source VARCHAR(16)"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_store_id UUID"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS address TEXT"))
        connection.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS feedback TEXT"))

        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1
                        FROM pg_constraint
                        WHERE conname = 'users_last_store_id_fkey'
                    ) THEN
                        ALTER TABLE users
                        ADD CONSTRAINT users_last_store_id_fkey
                        FOREIGN KEY (last_store_id) REFERENCES stores(id) ON DELETE SET NULL;
                    END IF;
                END
                $$;
                """
            )
        )

        connection.execute(text("CREATE INDEX IF NOT EXISTS idx_users_last_store_id ON users(last_store_id)"))
        connection.execute(text("UPDATE users SET provider = 'local' WHERE provider IS NULL"))
        connection.execute(text("UPDATE users SET source = 'WEBSITE' WHERE source IS NULL"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN provider SET DEFAULT 'local'"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN provider SET NOT NULL"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN source SET DEFAULT 'WEBSITE'"))
        connection.execute(text("ALTER TABLE users ALTER COLUMN source SET NOT NULL"))

        connection.execute(text("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_source_check"))
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD CONSTRAINT users_source_check
                CHECK (source IN ('WEBSITE', 'STORE', 'ADMIN'))
                """
            )
        )

        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_source ON users (source)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_provider ON users (provider)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_users_provider_id ON users (provider_id)"))
        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_users_provider_provider_id
                ON users (provider, provider_id)
                WHERE provider_id IS NOT NULL
                """
            )
        )

        _migrate_legacy_sales_customers_to_users(connection)

        connection.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS uq_addresses_default_per_user
                ON addresses (user_id)
                WHERE is_default IS TRUE
                """
            )
        )


# M-5 FIX: Use the same strict email regex that normalize_admin_email uses in
# admin_auth.py. The previous check only verified that "@" appeared somewhere in
# the string, accepting malformed values like "a@", "@b", and "a@b" which cause
# downstream email delivery failures and uniqueness constraint confusion.
_USER_EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def normalize_user_email(email: str) -> str:
    normalized = email.strip().lower()
    # M-5 FIX: Validate against a proper email regex, not just "@" presence.
    if not normalized or not _USER_EMAIL_REGEX.match(normalized):
        raise HTTPException(status_code=400, detail="A valid email address is required")
    return normalized


def hash_user_password(password: str) -> str:
    normalized = password.strip()
    if len(normalized) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    return bcrypt.hashpw(normalized.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_user_password(password: str, encoded_hash: str) -> bool:
    if not password or not encoded_hash:
        return False

    try:
        return bcrypt.checkpw(password.encode("utf-8"), encoded_hash.encode("utf-8"))
    except Exception:
        return False


def create_user_access_token(*, user_id: str, email: str) -> str:
    now = int(time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "iat": now,
        "exp": now + _get_access_ttl_seconds(),
    }

    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_part = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_part}.{payload_part}"
    signature_part = _sign(signing_input, _get_secret())

    return f"{signing_input}.{signature_part}"


def decode_user_access_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid user token")

    header_part, payload_part, signature_part = parts
    signing_input = f"{header_part}.{payload_part}"
    expected_signature = _sign(signing_input, _get_secret())

    if not secrets.compare_digest(signature_part, expected_signature):
        raise HTTPException(status_code=401, detail="Invalid user token")

    try:
        payload_raw = _b64url_decode(payload_part)
        payload = json.loads(payload_raw)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid user token") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=401, detail="Invalid user token")

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp <= int(time.time()):
        raise HTTPException(status_code=401, detail="User token expired")

    return payload


def get_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization required")

    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization header")

    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Authorization required")

    return token


def get_user_token_payload(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    token = get_bearer_token(authorization)
    return decode_user_access_token(token)


def create_user_refresh_token(*, db: Session, user_id: UUID, user_agent: str | None = None) -> str:
    raw_refresh_token = secrets.token_urlsafe(48)
    token_record = UserRefreshToken(
        user_id=user_id,
        token_hash=_token_digest(raw_refresh_token),
        user_agent=user_agent,
        expires_at=_utcnow() + timedelta(seconds=_get_refresh_ttl_seconds()),
    )
    db.add(token_record)
    return raw_refresh_token


def issue_user_session_tokens(
    *,
    db: Session,
    user: User,
    user_agent: str | None = None,
) -> tuple[str, str]:
    access_token = create_user_access_token(user_id=str(user.id), email=user.email)
    refresh_token = create_user_refresh_token(db=db, user_id=user.id, user_agent=user_agent)
    return access_token, refresh_token


def rotate_user_refresh_token(
    *,
    db: Session,
    refresh_token: str,
    user_agent: str | None = None,
) -> tuple[User, str, str]:
    normalized_token = refresh_token.strip()
    if not normalized_token:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    now = _utcnow()
    token_hash = _token_digest(normalized_token)

    token_record = (
        db.query(UserRefreshToken)
        .filter(
            UserRefreshToken.token_hash == token_hash,
            UserRefreshToken.revoked_at.is_(None),
        )
        .first()
    )

    if token_record is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if token_record.expires_at <= now:
        token_record.revoked_at = now
        raise HTTPException(status_code=401, detail="Refresh token expired")

    user = (
        db.query(User)
        .filter(User.id == token_record.user_id, User.is_active.is_(True))
        .first()
    )

    if user is None:
        token_record.revoked_at = now
        raise HTTPException(status_code=401, detail="User not found or inactive")

    token_record.revoked_at = now
    new_refresh_token = create_user_refresh_token(db=db, user_id=user.id, user_agent=user_agent)
    token_record.replaced_by_token_hash = _token_digest(new_refresh_token)

    new_access_token = create_user_access_token(user_id=str(user.id), email=user.email)
    return user, new_access_token, new_refresh_token


def revoke_user_refresh_token(*, db: Session, refresh_token: str) -> bool:
    normalized_token = refresh_token.strip()
    if not normalized_token:
        return False

    token_hash = _token_digest(normalized_token)
    token_record = (
        db.query(UserRefreshToken)
        .filter(
            UserRefreshToken.token_hash == token_hash,
            UserRefreshToken.revoked_at.is_(None),
        )
        .first()
    )

    if token_record is None:
        return False

    token_record.revoked_at = _utcnow()
    return True


def revoke_all_user_refresh_tokens(*, db: Session, user_id: UUID) -> int:
    return (
        db.query(UserRefreshToken)
        .filter(UserRefreshToken.user_id == user_id, UserRefreshToken.revoked_at.is_(None))
        .update({"revoked_at": _utcnow()}, synchronize_session=False)
    )


def create_password_reset_token(*, db: Session, user_id: UUID) -> tuple[str, datetime]:
    now = _utcnow()
    (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.user_id == user_id, PasswordResetToken.used_at.is_(None))
        .update({"used_at": now}, synchronize_session=False)
    )

    raw_reset_token = secrets.token_urlsafe(48)
    expires_at = now + timedelta(seconds=_get_password_reset_ttl_seconds())

    token_record = PasswordResetToken(
        user_id=user_id,
        token_hash=_token_digest(raw_reset_token),
        expires_at=expires_at,
    )
    db.add(token_record)

    return raw_reset_token, expires_at


def consume_password_reset_token(*, db: Session, token: str) -> User:
    normalized_token = token.strip()
    if not normalized_token:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    token_record = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == _token_digest(normalized_token),
            PasswordResetToken.used_at.is_(None),
        )
        .first()
    )

    if token_record is None:
        raise HTTPException(status_code=400, detail="Invalid reset token")

    now = _utcnow()
    if token_record.expires_at <= now:
        token_record.used_at = now
        raise HTTPException(status_code=400, detail="Reset token expired")

    user = (
        db.query(User)
        .filter(User.id == token_record.user_id, User.is_active.is_(True))
        .first()
    )

    if user is None:
        token_record.used_at = now
        raise HTTPException(status_code=400, detail="Invalid reset token")

    token_record.used_at = now
    return user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token_payload: dict[str, Any] = Depends(get_user_token_payload),
) -> User:
    payload = getattr(request.state, "user_token_payload", token_payload)
    subject = payload.get("sub")

    if not isinstance(subject, str):
        raise HTTPException(status_code=401, detail="Invalid user token")

    try:
        user_id = UUID(subject)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid user token") from exc

    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()

    if user is None:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    request.state.current_user = user
    return user


def require_authenticated_user(_: User = Depends(get_current_user)) -> None:
    return None
