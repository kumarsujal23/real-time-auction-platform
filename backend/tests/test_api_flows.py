"""
End-to-end-ish tests through the actual FastAPI routes (register -> login ->
create auction -> list -> bid rejection for bad amount), using an
in-memory SQLite database via dependency override. This checks routing,
auth wiring, and schema validation together rather than each service in
isolation.
"""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.database import Base, get_db
from app.main import app

SQLITE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture
async def client():
    engine = create_async_engine(SQLITE_URL, connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


@pytest.mark.asyncio
async def test_register_login_and_create_auction(client: AsyncClient):
    register_resp = await client.post(
        "/api/auth/register",
        json={
            "email": "seller@example.com",
            "password": "supersecret123",
            "full_name": "Sam Seller",
            "role": "seller",
        },
    )
    assert register_resp.status_code == 201
    token = register_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    me_resp = await client.get("/api/users/me", headers=headers)
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "seller@example.com"

    create_resp = await client.post(
        "/api/auctions",
        headers=headers,
        json={
            "title": "Vintage Camera",
            "description": "Works great",
            "starting_price": 50,
            "min_increment": 5,
            "start_time": "2020-01-01T00:00:00Z",  # already started
            "end_time": "2099-01-01T00:00:00Z",
        },
    )
    assert create_resp.status_code == 201
    auction = create_resp.json()
    assert auction["status"] == "active"

    list_resp = await client.get("/api/auctions")
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_duplicate_email_registration_rejected(client: AsyncClient):
    payload = {
        "email": "dupe@example.com",
        "password": "supersecret123",
        "full_name": "Dupe One",
        "role": "buyer",
    }
    first = await client.post("/api/auth/register", json=payload)
    assert first.status_code == 201
    second = await client.post("/api/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_bid_too_low_returns_422(client: AsyncClient):
    seller_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "seller2@example.com",
            "password": "supersecret123",
            "full_name": "Seller Two",
            "role": "seller",
        },
    )
    seller_headers = {"Authorization": f"Bearer {seller_reg.json()['access_token']}"}

    buyer_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "buyer2@example.com",
            "password": "supersecret123",
            "full_name": "Buyer Two",
            "role": "buyer",
        },
    )
    buyer_headers = {"Authorization": f"Bearer {buyer_reg.json()['access_token']}"}

    create_resp = await client.post(
        "/api/auctions",
        headers=seller_headers,
        json={
            "title": "Guitar",
            "description": "",
            "starting_price": 100,
            "min_increment": 10,
            "start_time": "2020-01-01T00:00:00Z",
            "end_time": "2099-01-01T00:00:00Z",
        },
    )
    auction_id = create_resp.json()["id"]

    bid_resp = await client.post(
        f"/api/auctions/{auction_id}/bids",
        headers=buyer_headers,
        json={"amount": 100, "idempotency_key": "k1"},  # must be >= 110
    )
    assert bid_resp.status_code == 422

    good_bid_resp = await client.post(
        f"/api/auctions/{auction_id}/bids",
        headers=buyer_headers,
        json={"amount": 110, "idempotency_key": "k2"},
    )
    assert good_bid_resp.status_code == 201
    assert good_bid_resp.json()["amount"] == 110.0


@pytest.mark.asyncio
async def test_seller_cannot_bid_on_own_auction_via_api(client: AsyncClient):
    seller_reg = await client.post(
        "/api/auth/register",
        json={
            "email": "seller3@example.com",
            "password": "supersecret123",
            "full_name": "Seller Three",
            "role": "seller",
        },
    )
    seller_headers = {"Authorization": f"Bearer {seller_reg.json()['access_token']}"}

    create_resp = await client.post(
        "/api/auctions",
        headers=seller_headers,
        json={
            "title": "Watch",
            "description": "",
            "starting_price": 100,
            "min_increment": 10,
            "start_time": "2020-01-01T00:00:00Z",
            "end_time": "2099-01-01T00:00:00Z",
        },
    )
    auction_id = create_resp.json()["id"]

    bid_resp = await client.post(
        f"/api/auctions/{auction_id}/bids",
        headers=seller_headers,
        json={"amount": 150, "idempotency_key": "k3"},
    )
    assert bid_resp.status_code == 403
