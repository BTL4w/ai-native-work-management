"""PostgreSQL-backed login, session, logout, audit, and tenant-boundary tests."""

from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from pwdlib import PasswordHash
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import create_database_engine
from app.main import create_app

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_POSTGRES_INTEGRATION") != "1",
        reason="set RUN_POSTGRES_INTEGRATION=1 with local PostgreSQL running",
    ),
]


@pytest.mark.asyncio
async def test_local_auth_session_audit_and_tenant_locator_boundary() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    membership_id = uuid4()
    slug = f"auth-test-{organization_id.hex}"
    email = f"auth-{user_id.hex}@example.test"
    password = "IntegrationAuth123!"
    cookie_name = "auth_test_session"
    request_prefix = uuid4().hex
    settings = Settings(
        environment="test",
        local_auth_organization_slug=slug,
        session_cookie_name=cookie_name,
    )
    admin_engine = create_database_engine(settings)

    try:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO organizations (id, slug, name) "
                    "VALUES (:id, :slug, 'Auth Test Organization')"
                ),
                {"id": organization_id, "slug": slug},
            )
            await connection.execute(
                text(
                    "INSERT INTO users "
                    "(id, email_normalized, email_display, display_name, password_hash) "
                    "VALUES (:id, :email, :email, 'Auth Test Manager', :password_hash)"
                ),
                {
                    "id": user_id,
                    "email": email,
                    "password_hash": PasswordHash.recommended().hash(password),
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO memberships (id, organization_id, user_id, role) "
                    "VALUES (:id, :organization_id, :user_id, 'MANAGER')"
                ),
                {"id": membership_id, "organization_id": organization_id, "user_id": user_id},
            )

        app = create_app(settings)
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            missing = await client.get("/api/v1/me")
            assert missing.status_code == 401
            assert missing.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"

            unknown_request_id = f"{request_prefix}-unknown"
            unknown = await client.post(
                "/api/v1/auth/login",
                json={"email": "unknown@example.test", "password": "wrong"},
                headers={"X-Request-ID": unknown_request_id},
            )
            assert unknown.status_code == 401
            assert unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"

            rejected_request_id = f"{request_prefix}-rejected"
            rejected = await client.post(
                "/api/v1/auth/login",
                json={"email": email, "password": "wrong"},
                headers={"X-Request-ID": rejected_request_id},
            )
            assert rejected.status_code == 401
            assert rejected.json()["error"]["code"] == "INVALID_CREDENTIALS"

            login_request_id = f"{request_prefix}-login"
            login = await client.post(
                "/api/v1/auth/login",
                json={"email": f"  {email.upper()}  ", "password": password},
                headers={"X-Request-ID": login_request_id},
            )
            assert login.status_code == 200
            assert login.json() == {
                "user": {
                    "id": str(user_id),
                    "email": email,
                    "display_name": "Auth Test Manager",
                },
                "membership": {
                    "id": str(membership_id),
                    "organization_id": str(organization_id),
                    "organization_name": "Auth Test Organization",
                    "role": "MANAGER",
                },
            }
            set_cookie = login.headers["set-cookie"]
            assert "HttpOnly" in set_cookie
            assert "SameSite=lax" in set_cookie
            cookie_value = client.cookies[cookie_name]

            current = await client.get("/api/v1/me")
            assert current.status_code == 200
            assert current.json() == login.json()

            _, raw_token = cookie_value.split(".", maxsplit=1)
            async with AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as tampered_client:
                tampered_client.cookies.set(cookie_name, f"{uuid4()}.{raw_token}")
                cross_tenant = await tampered_client.get("/api/v1/me")
                assert cross_tenant.status_code == 401
                assert cross_tenant.json()["error"]["code"] == "SESSION_EXPIRED"

            logout_request_id = f"{request_prefix}-logout"
            logout = await client.post(
                "/api/v1/auth/logout",
                headers={"X-Request-ID": logout_request_id},
            )
            assert logout.status_code == 204
            assert cookie_name not in client.cookies

            repeated_logout = await client.post("/api/v1/auth/logout")
            assert repeated_logout.status_code == 204

            client.cookies.set(cookie_name, cookie_value)
            revoked = await client.get("/api/v1/me")
            assert revoked.status_code == 401
            assert revoked.json()["error"]["code"] == "SESSION_EXPIRED"

        database_engine = app.state.database_engine
        assert database_engine is not None
        await database_engine.dispose()

        expected_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        async with admin_engine.connect() as connection:
            stored_token_hash = await connection.scalar(
                text(
                    "SELECT token_hash FROM auth_sessions WHERE organization_id = :organization_id"
                ),
                {"organization_id": organization_id},
            )
            assert stored_token_hash == expected_token_hash
            assert stored_token_hash != raw_token

            audit_rows = (
                await connection.execute(
                    text(
                        "SELECT action, outcome::text, request_id, reason_data::text "
                        "FROM audit_events WHERE organization_id = :organization_id "
                        "ORDER BY occurred_at, id"
                    ),
                    {"organization_id": organization_id},
                )
            ).all()
            assert [(row.action, row.outcome) for row in audit_rows] == [
                ("auth.login.rejected", "REJECTED"),
                ("auth.login.succeeded", "SUCCEEDED"),
                ("auth.logout.succeeded", "SUCCEEDED"),
            ]
            assert [row.request_id for row in audit_rows] == [
                rejected_request_id,
                login_request_id,
                logout_request_id,
            ]
            assert all(password not in row.reason_data for row in audit_rows)
            unknown_audit_count = await connection.scalar(
                text("SELECT count(*) FROM audit_events WHERE request_id = :request_id"),
                {"request_id": unknown_request_id},
            )
            assert unknown_audit_count == 0
    finally:
        async with admin_engine.begin() as connection:
            await connection.execute(
                text("DELETE FROM audit_events WHERE organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM auth_sessions WHERE organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM memberships WHERE organization_id = :organization_id"),
                {"organization_id": organization_id},
            )
            await connection.execute(
                text("DELETE FROM users WHERE id = :user_id"), {"user_id": user_id}
            )
            await connection.execute(
                text("DELETE FROM organizations WHERE id = :organization_id"),
                {"organization_id": organization_id},
            )
        await admin_engine.dispose()
