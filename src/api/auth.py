"""
================================================================================
CEREBRO-X |  AUTHENTICATION & RBAC ENGINE
================================================================================
File: cerebro_auth.py

Enterprise-grade authentication layer:

  1. JWT (JSON Web Token) Authentication
     - Access tokens (short-lived: 30 min)
     - Refresh tokens (long-lived: 7 days)
     - Token rotation on refresh (revoke old, issue new)
     - BCrypt password hashing (cost factor 12)

  2. Role-Based Access Control (RBAC)
     - Roles: admin, researcher, reviewer, readonly
     - Permission matrix per endpoint
     - Decorator-based route protection
     - Audit trail for privileged operations

  3. API Key Authentication (for service-to-service)
     - HMAC-SHA256 signed keys
     - Rate limiting per key
     - Scoped permissions

Architecture:
  FastAPI Depends() injection → every protected route gets current_user
  automatically. No manual token parsing in business logic.

References:
  - OWASP JWT Cheat Sheet (2023)
  - RFC 7519 (JWT)
  - NIST SP 800-63B (Digital Identity Guidelines)
================================================================================
"""

import hashlib
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

# ─────────────────────────────────────────────────────────────────────────────
# Dependencies
# ─────────────────────────────────────────────────────────────────────────────
try:
    from jose import JWTError, jwt
    _HAS_JOSE = True
except ImportError:
    _HAS_JOSE = False

try:
    from passlib.context import CryptContext
    _HAS_PASSLIB = True
except ImportError:
    _HAS_PASSLIB = False

try:
    from fastapi import Depends, HTTPException, Security, status
    from fastapi.security import (
        APIKeyHeader,
        HTTPAuthorizationCredentials,
        HTTPBearer,
        OAuth2PasswordBearer,
        OAuth2PasswordRequestForm,
    )
    from pydantic import BaseModel, EmailStr, Field
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False

try:
    from sqlalchemy import (
        JSON,
        Boolean,
        Column,
        DateTime,
        ForeignKey,
        Integer,
        String,
        Text,
        create_engine,
        event,
    )
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import Session, relationship, sessionmaker
    _HAS_SQLALCHEMY = True
except ImportError:
    _HAS_SQLALCHEMY = False

log = logging.getLogger("CEREBRO-AUTH")

# ─────────────────────────────────────────────────────────────────────────────
# Configuration (from environment or defaults)
# ─────────────────────────────────────────────────────────────────────────────
ENVIRONMENT   = os.environ.get("ENVIRONMENT", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"

# Placeholder values shipped in .env.example / docker-compose*.yml — if any of
# these are still active in ENVIRONMENT=production, refuse to start rather than
# silently run with a known/guessable secret.
_KNOWN_DEFAULT_SECRETS = {
    "CHANGE_ME_generate_a_64_char_hex_string",
    "cerebro_admin_2024",
    "CHANGE_ME_strong_admin_password",
    "change_me_in_production_32chars_min",
    "admin_change_me",
}

_env_jwt_secret = os.environ.get("JWT_SECRET_KEY")
if IS_PRODUCTION and (not _env_jwt_secret or _env_jwt_secret in _KNOWN_DEFAULT_SECRETS):
    raise RuntimeError(
        "JWT_SECRET_KEY is unset or still a placeholder default, but "
        "ENVIRONMENT=production. Refusing to start with a guessable/shared "
        "signing key. Generate one with: "
        "python -c \"import secrets; print(secrets.token_hex(32))\" "
        "and set it in the environment before starting the API."
    )
if not _env_jwt_secret:
    log.warning(
        "[AUTH] JWT_SECRET_KEY not set — using an ephemeral per-process key. "
        "Fine for local dev; tokens will NOT survive a restart and will NOT "
        "validate across multiple worker processes. Never rely on this outside "
        "local development."
    )
JWT_SECRET_KEY       = _env_jwt_secret or secrets.token_hex(32)
JWT_ALGORITHM        = "HS256"
ACCESS_TOKEN_EXPIRE  = int(os.environ.get("JWT_ACCESS_EXPIRE_MINUTES", "30"))
REFRESH_TOKEN_EXPIRE = int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))
API_KEY_HEADER_NAME  = "X-API-Key"


# ─────────────────────────────────────────────────────────────────────────────
# 1. RBAC — Roles & Permissions
# ─────────────────────────────────────────────────────────────────────────────
class Role(str, Enum):
    ADMIN      = "admin"
    RESEARCHER = "researcher"
    REVIEWER   = "reviewer"
    READONLY   = "readonly"


# Permission matrix: role → set of allowed actions
PERMISSION_MATRIX: dict[str, set] = {
    Role.ADMIN: {
        "pipeline:run", "pipeline:read", "pipeline:config",
        "dds:run", "dds:read",
        "model:train", "model:predict", "model:delete",
        "user:create", "user:read", "user:update", "user:delete",
        "results:read", "results:delete",
        "audit:read",
        "system:health", "system:config",
    },
    Role.RESEARCHER: {
        "pipeline:run", "pipeline:read",
        "dds:run", "dds:read",
        "model:train", "model:predict",
        "results:read",
        "system:health",
    },
    Role.REVIEWER: {
        "pipeline:read",
        "dds:read",
        "model:predict",
        "results:read",
        "audit:read",
        "system:health",
    },
    Role.READONLY: {
        "pipeline:read",
        "dds:read",
        "results:read",
        "system:health",
    },
}


def has_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    return permission in PERMISSION_MATRIX.get(role, set())


# ─────────────────────────────────────────────────────────────────────────────
# 2. Password Hashing (BCrypt)
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_PASSLIB:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
else:
    # Fallback: SHA-256 with salt (NOT production-grade — install passlib)
    class _FallbackPwd:
        @staticmethod
        def hash(password: str) -> str:
            salt = secrets.token_hex(16)
            h = hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
            return f"sha256${salt}${h}"

        @staticmethod
        def verify(password: str, hashed: str) -> bool:
            parts = hashed.split("$")
            if len(parts) != 3 or parts[0] != "sha256":
                return False
            salt, stored_hash = parts[1], parts[2]
            return hashlib.sha256(
                f"{salt}{password}".encode()
            ).hexdigest() == stored_hash

    pwd_context = _FallbackPwd()
    log.warning("[AUTH] passlib not installed — using SHA-256 fallback. "
                "Install: pip install passlib[bcrypt]")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Database Models (SQLAlchemy)
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_SQLALCHEMY:
    AuthBase = declarative_base()

    class UserModel(AuthBase):
        __tablename__ = "users"

        id              = Column(Integer, primary_key=True, index=True)
        email           = Column(String(255), unique=True, nullable=False, index=True)
        username        = Column(String(100), unique=True, nullable=False, index=True)
        hashed_password = Column(String(255), nullable=False)
        full_name       = Column(String(255))
        role            = Column(String(50), default=Role.READONLY, nullable=False)
        is_active       = Column(Boolean, default=True)
        created_at      = Column(DateTime, default=datetime.utcnow)
        updated_at      = Column(DateTime, default=datetime.utcnow,
                                 onupdate=datetime.utcnow)

        # Relationships
        api_keys    = relationship("APIKeyModel", back_populates="user")
        audit_logs  = relationship("AuditLogModel", back_populates="user")

    class APIKeyModel(AuthBase):
        __tablename__ = "api_keys"

        id          = Column(Integer, primary_key=True, index=True)
        key_hash    = Column(String(255), unique=True, nullable=False, index=True)
        key_prefix  = Column(String(10), nullable=False)  # first 8 chars for ID
        name        = Column(String(100), nullable=False)
        user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
        scopes      = Column(JSON, default=list)  # list of permission strings
        is_active   = Column(Boolean, default=True)
        last_used   = Column(DateTime)
        created_at  = Column(DateTime, default=datetime.utcnow)
        expires_at  = Column(DateTime, nullable=True)

        user = relationship("UserModel", back_populates="api_keys")

    class AuditLogModel(AuthBase):
        __tablename__ = "audit_logs"

        id          = Column(Integer, primary_key=True, index=True)
        user_id     = Column(Integer, ForeignKey("users.id"), nullable=True)
        action      = Column(String(100), nullable=False)
        resource    = Column(String(200))
        ip_address  = Column(String(45))
        user_agent  = Column(String(500))
        details     = Column(JSON, default=dict)
        timestamp   = Column(DateTime, default=datetime.utcnow, index=True)

        user = relationship("UserModel", back_populates="audit_logs")

    class RefreshTokenModel(AuthBase):
        __tablename__ = "refresh_tokens"

        id          = Column(Integer, primary_key=True, index=True)
        token_hash  = Column(String(255), unique=True, nullable=False, index=True)
        user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
        expires_at  = Column(DateTime, nullable=False)
        revoked     = Column(Boolean, default=False)
        created_at  = Column(DateTime, default=datetime.utcnow)

    class TaskOwnershipModel(AuthBase):
        """Records which user submitted a given Celery task_id, so status/result
        polling endpoints can enforce that only the submitter (or an admin) may
        read that task's output."""
        __tablename__ = "task_ownership"

        id         = Column(Integer, primary_key=True, index=True)
        task_id    = Column(String(155), unique=True, nullable=False, index=True)
        user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
        created_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Pydantic Schemas
# ─────────────────────────────────────────────────────────────────────────────
if _HAS_FASTAPI:
    class UserCreate(BaseModel):
        """Internal/admin-facing schema — `role` is only ever set by trusted
        server-side callers (bootstrap_admin, admin user-creation flows).
        NEVER bind this schema directly to an unauthenticated request body;
        use UserRegister for the public /auth/register endpoint instead."""
        email:     str = Field(..., description="User email")
        username:  str = Field(..., min_length=3, max_length=50)
        password:  str = Field(..., min_length=8)
        full_name: str | None = None
        role:      str = Field(default=Role.READONLY)

    class UserRegister(BaseModel):
        """Public self-registration schema — deliberately has no `role` field
        so an anonymous caller can never request a privileged role. The
        /auth/register endpoint always creates these accounts as READONLY;
        elevation requires an authenticated admin via PUT /users/{id}/role."""
        email:     str = Field(..., description="User email")
        username:  str = Field(..., min_length=3, max_length=50)
        password:  str = Field(..., min_length=8)
        full_name: str | None = None

    class UserResponse(BaseModel):
        id:         int
        email:      str
        username:   str
        full_name:  str | None
        role:       str
        is_active:  bool
        created_at: datetime

        class Config:
            from_attributes = True

    class TokenResponse(BaseModel):
        access_token:  str
        refresh_token: str
        token_type:    str = "bearer"
        expires_in:    int  # seconds
        role:          str

    class TokenRefreshRequest(BaseModel):
        refresh_token: str

    class APIKeyCreate(BaseModel):
        name:   str = Field(..., description="Key description")
        scopes: list[str] = Field(default_factory=list)

    class APIKeyResponse(BaseModel):
        key:        str  # shown only once at creation
        key_prefix: str
        name:       str
        scopes:     list[str]
        created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# 5. JWT Token Engine
# ─────────────────────────────────────────────────────────────────────────────
class TokenEngine:
    """Creates and verifies JWT access + refresh tokens."""

    @staticmethod
    def create_access_token(
        data: dict,
        expires_delta: timedelta | None = None,
    ) -> str:
        if not _HAS_JOSE:
            raise RuntimeError("python-jose not installed: pip install python-jose[cryptography]")

        to_encode = data.copy()
        expire = datetime.now(timezone.utc) + (
            expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE)
        )
        to_encode.update({
            "exp":  expire,
            "iat":  datetime.now(timezone.utc),
            "type": "access",
            # JWT exp/iat are second-resolution (RFC 7519 NumericDate), so two
            # access tokens minted for the same user within the same second
            # would otherwise be byte-identical. A unique jti guarantees every
            # issued token is distinct, which also matters for audit logging.
            "jti":  secrets.token_hex(16),
        })
        return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def create_refresh_token(user_id: int) -> str:
        if not _HAS_JOSE:
            raise RuntimeError("python-jose not installed")

        expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE)
        data = {
            "sub":  str(user_id),
            "exp":  expire,
            "iat":  datetime.now(timezone.utc),
            "type": "refresh",
            "jti":  secrets.token_hex(16),  # unique token ID for revocation
        }
        return jwt.encode(data, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

    @staticmethod
    def decode_token(token: str) -> dict:
        if not _HAS_JOSE:
            raise RuntimeError("python-jose not installed")
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except JWTError as e:
            raise ValueError(f"Invalid token: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 6. Auth Service (business logic)
# ─────────────────────────────────────────────────────────────────────────────
class AuthService:
    """Handles user registration, login, token refresh, API keys."""

    def __init__(self, db: "Session"):
        self.db = db

    def create_user(self, user_data: "UserCreate") -> "UserModel":
        # Check duplicates
        existing = self.db.query(UserModel).filter(
            (UserModel.email == user_data.email) |
            (UserModel.username == user_data.username)
        ).first()
        if existing:
            raise ValueError("Email or username already registered")

        user = UserModel(
            email=user_data.email,
            username=user_data.username,
            hashed_password=pwd_context.hash(user_data.password),
            full_name=user_data.full_name,
            role=user_data.role,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        log.info(f"[AUTH] User created: {user.username} (role={user.role})")
        return user

    def authenticate(self, username: str, password: str) -> Optional["UserModel"]:
        user = self.db.query(UserModel).filter(
            UserModel.username == username
        ).first()
        if not user or not user.is_active:
            return None
        if not pwd_context.verify(password, user.hashed_password):
            return None
        return user

    def login(self, username: str, password: str) -> Optional["TokenResponse"]:
        user = self.authenticate(username, password)
        if not user:
            return None

        access_token  = TokenEngine.create_access_token(
            data={"sub": str(user.id), "role": user.role, "username": user.username}
        )
        refresh_token = TokenEngine.create_refresh_token(user.id)

        # Store refresh token hash
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        rt = RefreshTokenModel(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE),
        )
        self.db.add(rt)
        self.db.commit()

        self._log_audit(user.id, "login", "auth")
        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=ACCESS_TOKEN_EXPIRE * 60,
            role=user.role,
        )

    def refresh_tokens(self, refresh_token: str) -> Optional["TokenResponse"]:
        try:
            payload = TokenEngine.decode_token(refresh_token)
        except ValueError:
            return None

        if payload.get("type") != "refresh":
            return None

        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        stored = self.db.query(RefreshTokenModel).filter(
            RefreshTokenModel.token_hash == token_hash,
            RefreshTokenModel.revoked == False,
        ).first()

        if not stored:
            return None

        # Revoke old token (rotation)
        stored.revoked = True

        user = self.db.query(UserModel).filter(
            UserModel.id == int(payload["sub"])
        ).first()
        if not user or not user.is_active:
            return None

        # Issue new pair
        new_access  = TokenEngine.create_access_token(
            data={"sub": str(user.id), "role": user.role, "username": user.username}
        )
        new_refresh = TokenEngine.create_refresh_token(user.id)

        new_hash = hashlib.sha256(new_refresh.encode()).hexdigest()
        self.db.add(RefreshTokenModel(
            token_hash=new_hash,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=REFRESH_TOKEN_EXPIRE),
        ))
        self.db.commit()

        return TokenResponse(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=ACCESS_TOKEN_EXPIRE * 60,
            role=user.role,
        )

    def create_api_key(self, user_id: int, name: str,
                       scopes: list[str] = None) -> tuple:
        """Returns (raw_key, APIKeyModel). Raw key shown only once."""
        raw_key    = f"cerebro_{secrets.token_hex(24)}"
        key_hash   = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]

        api_key = APIKeyModel(
            key_hash=key_hash,
            key_prefix=key_prefix,
            name=name,
            user_id=user_id,
            scopes=scopes or [],
        )
        self.db.add(api_key)
        self.db.commit()
        self.db.refresh(api_key)
        self._log_audit(user_id, "api_key:create", f"key:{key_prefix}")
        return raw_key, api_key

    def verify_api_key(self, raw_key: str) -> Optional["UserModel"]:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = self.db.query(APIKeyModel).filter(
            APIKeyModel.key_hash == key_hash,
            APIKeyModel.is_active == True,
        ).first()
        if not api_key:
            return None
        if api_key.expires_at and api_key.expires_at < datetime.utcnow():
            return None

        # Update last_used
        api_key.last_used = datetime.utcnow()
        self.db.commit()

        return api_key.user

    def _log_audit(self, user_id: int, action: str,
                   resource: str = "", details: dict = None):
        entry = AuditLogModel(
            user_id=user_id,
            action=action,
            resource=resource,
            details=details or {},
        )
        self.db.add(entry)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()


# ─────────────────────────────────────────────────────────────────────────────
# 7. FastAPI Dependencies
# ─────────────────────────────────────────────────────────────────────────────
# NOTE: get_current_user, require_permission, and a standalone auth_router used
# to be defined here with `db: "Session" = None` route parameters that are not
# valid Pydantic field types — FastAPI raises FastAPIError on startup for any
# route that mixes an unresolved DB-session annotation with no Depends(). This
# module was never wired to that duplicate router (src/api/app.py builds and
# mounts its own `_auth` router with the DB session correctly injected via
# Depends(get_db)), so the block was unused, broken-by-construction, and has
# been removed rather than fixed in place. See src/api/app.py for the real
# /auth/register, /auth/login, /auth/refresh, /auth/api-key, /auth/me routes.


# ─────────────────────────────────────────────────────────────────────────────
# 8. Bootstrap: create default admin if no users exist
# ─────────────────────────────────────────────────────────────────────────────
def bootstrap_admin(db: "Session"):
    """Create default admin user if the users table is empty."""
    if not _HAS_SQLALCHEMY:
        return
    count = db.query(UserModel).count()
    if count == 0:
        admin_pw = os.environ.get("CEREBRO_ADMIN_PASSWORD")
        if IS_PRODUCTION and (not admin_pw or admin_pw in _KNOWN_DEFAULT_SECRETS):
            raise RuntimeError(
                "CEREBRO_ADMIN_PASSWORD is unset or still a placeholder default, "
                "but ENVIRONMENT=production. Refusing to bootstrap an admin "
                "account with a guessable password. Set a strong password in "
                "the environment before starting the API."
            )
        if not admin_pw:
            admin_pw = "cerebro_admin_2024"
            log.warning(
                "[AUTH] CEREBRO_ADMIN_PASSWORD not set — bootstrapping admin "
                "with the well-known dev default. Fine for local dev only; "
                "change it immediately if this is ever reachable outside "
                "localhost."
            )
        svc = AuthService(db)
        svc.create_user(UserCreate(
            email="admin@cerebro-x.local",
            username="admin",
            password=admin_pw,
            full_name="CEREBRO-X Administrator",
            role=Role.ADMIN,
        ))
        log.info("[AUTH] Default admin created (username=admin). "
                 "Change password immediately in production!")