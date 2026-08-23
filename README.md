# Real-Time Auction Platform

A production-inspired full-stack timed-auction system built as a portfolio
project. Sellers list timed auctions, buyers bid in real time over
WebSockets, and a background worker resolves winners the moment an
auction's clock runs out — all with a database design that makes
concurrent-bidding race conditions structurally impossible rather than
"unlikely."

This README is written so you can use it as interview prep: every
non-obvious decision below is something you should be able to explain and
defend out loud.

---

## Stack

| Layer          | Choice                                             |
|----------------|-----------------------------------------------------|
| Frontend       | React + TypeScript + Vite                          |
| Backend        | Python + FastAPI (async)                            |
| Database       | PostgreSQL + SQLAlchemy 2.0 (async) + Alembic       |
| Cache/Fan-out  | Redis (Pub/Sub only — not a data store)             |
| Realtime       | Native WebSockets                                   |
| Background job | Standalone polling worker process                   |
| Infra          | Docker Compose                                       |
| Tests          | Pytest (unit + real-Postgres concurrency) + Playwright |
| CI             | GitHub Actions                                       |

---

## Architecture

```
 React (Vite)
     │  HTTP (REST) + WebSocket
     ▼
 FastAPI ─────────────┬─────────────────────┐
   ├── Auth            │                     │
   ├── Auction API      │                     │
   ├── Bid Service      ▼                     ▼
   ├── WS Manager    PostgreSQL            Redis (Pub/Sub)
   └── (worker runs as its own process,
        NOT inside the API process)
              │
              ▼
        Background Worker
     (auction activation / expiry / winner selection)
```

**Why Redis is only Pub/Sub, never a cache-of-record:** the current price
and bid history live in Postgres and nowhere else. Redis exists solely so
that a bid accepted by backend instance A can be pushed to a buyer whose
WebSocket happens to be held open by instance B. If Redis went down, bids
would still be accepted and persisted correctly — you'd just lose live
push updates until clients reconnect and re-fetch from the REST API. That
asymmetry (Postgres = source of truth, Redis = disposable fan-out) is the
whole reason to reach for Pub/Sub instead of, say, keeping `current_price`
in Redis for speed.

**Why the worker is a separate process, not a FastAPI background task:**
`docker-compose.yml` runs `backend` (the API) and `worker` as two
containers from the same image, with the API's own in-process copy
disabled via `RUN_WORKER_IN_PROCESS=false`. This means you can scale API
replicas and worker replicas independently, and a slow/crashed worker tick
never blocks request handling. (For quick local `uvicorn` runs without
Docker, `app/main.py` will spin up an in-process worker automatically so
you don't need two terminals just to see auctions expire.)

---

## The concurrency story (the part to actually understand cold)

The single most important file in this repo is
[`backend/app/services/bid_service.py`](backend/app/services/bid_service.py).

The naive way to implement "place a bid" is:

```python
auction = SELECT * FROM auctions WHERE id = :id        # read
if amount > auction.current_price:                      # compare
    UPDATE auctions SET current_price = amount           # write
```

This is a textbook **check-then-act race**. If two buyers bid within
microseconds of each other, both requests can read the *same*
`current_price`, both pass the `if`, and both writes "succeed" — whichever
transaction commits last silently wins, even if it bid a *lower* amount
than the other request believed it was beating. Under load this isn't a
theoretical edge case; it's the first thing that breaks in any auction
system that skips this.

**The fix — pessimistic row-level locking:**

```python
async with transaction:
    auction = SELECT * FROM auctions WHERE id = :id FOR UPDATE   # (1)
    # (2) re-validate status / time window / amount against the
    #     row we JUST locked, not a stale read from before
    INSERT INTO bids (...)
    UPDATE auctions SET current_price = :amount, version = version + 1
    # COMMIT releases the lock                                    # (3)
```

`SELECT ... FOR UPDATE` takes a row-level exclusive lock scoped to that one
`auctions` row. A second concurrent bid for the **same** auction blocks at
its own `SELECT ... FOR UPDATE` until the first transaction commits or
rolls back — at which point it sees the *fresh* `current_price` and is
correctly rejected if it's no longer high enough. Bids on **different**
auctions are completely unaffected, since the lock is per-row, not a table
lock, so throughput across auctions stays fully parallel.

This is deliberately pessimistic locking rather than optimistic
retry-on-conflict: on a hot, correctness-sensitive, money-adjacent write
path, "block briefly then proceed correctly" is much easier to reason
about (and load-test) than "retry with backoff and hope the contention
window is short."

**Idempotency keys** (`Bid.idempotency_key`, unique per `(auction_id,
key)`) solve a *different* problem: a client-side retry (double-click, a
dropped response after the server actually committed) must never be
double-counted as a second bid. The service checks for an existing bid
with that key before doing anything else, and the database's unique
constraint is a second line of defense if two retries of the *same*
request somehow race each other.

**The background worker's own concurrency story:** finalizing an expired
auction uses `SELECT ... FOR UPDATE SKIP LOCKED` (see
`_finalize_one_expired_auction` in
[`auction_worker.py`](backend/app/workers/auction_worker.py)). This makes
it safe to run *multiple* worker replicas: if two workers poll at the same
moment, one claims the row and the other's query simply skips it (instead
of blocking, or double-creating an `Order`) and moves to the next expired
auction.

All three of these are exercised directly in
[`tests/test_concurrent_bidding.py`](backend/tests/test_concurrent_bidding.py)
and
[`tests/test_auction_expiry.py`](backend/tests/test_auction_expiry.py),
using real concurrent asyncio tasks against a real Postgres instance (not
mocked) — SQLite's locking model isn't representative enough for this to
mean anything, which is also why those tests are marked `@pytest.mark.postgres`
and skip themselves if no Postgres is reachable.

---

## Auction lifecycle

```
CREATED → SCHEDULED → ACTIVE → ENDED → COMPLETED
```

- `CREATED`/`SCHEDULED` → `ACTIVE` and `ACTIVE` → `ENDED` are **time-driven**,
  decided by the background worker comparing `now()` to `start_time` /
  `end_time` — never by a client request. This means the wall clock is the
  single source of truth for when bidding opens and closes, and no user
  action can accidentally start or stop an auction early.
- `bid_service.place_bid` independently re-checks `status == ACTIVE` and
  `start_time <= now < end_time` on every bid, so even if the worker is
  delayed by a tick, a bid arriving after `end_time` is still rejected.
- `ENDED → COMPLETED` happens in the same worker transaction that picks
  the winner (highest bid, ties broken by earliest timestamp) and creates
  an `Order` — or completes with no winner if there were no bids at all.

---

## Project layout

```
backend/
  app/
    api/          # HTTP + WebSocket route handlers (thin — no business logic)
    models/        # SQLAlchemy ORM models
    schemas/        # Pydantic request/response contracts
    services/       # Business logic (bid_service is the important one)
    websocket/      # Redis-Pub/Sub-backed connection manager
    workers/        # Standalone auction-expiry worker
    db/             # Engine/session setup + Alembic migrations
    core/           # Config (pydantic-settings) + JWT/password hashing
  tests/            # pytest: unit (SQLite) + concurrency (real Postgres)
frontend/
  src/
    pages/          # Route-level components (list, detail, dashboards, auth)
    hooks/          # useAuctionSocket (WS + reconnect), useCountdown
    services/       # Typed fetch wrapper
    context/        # AuthContext (JWT in localStorage)
    types/          # Mirrors backend Pydantic schemas
  e2e/              # Playwright smoke test (full stack, two browser contexts)
```

Each layer only talks to the one below it: routes call services, services
touch models/DB, nothing reaches into the WebSocket manager except
`notification_service.py`. This is what makes the concurrency-critical
code in `bid_service.py` unit-testable in isolation from HTTP/WS concerns.

---

## Running it

### With Docker Compose (recommended)

```bash
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API docs (Swagger): http://localhost:8000/docs
- Postgres: localhost:5432 (user/pass/db: `auction`/`auction`/`auction_db`)
- Redis: localhost:6379

Migrations run automatically on container start (see
`backend/docker-entrypoint.sh`).

The Compose credentials are for local development only. Do not reuse them in
production. The database and Redis ports are bound to localhost so they are
not exposed to the wider network.

### Locally, without Docker

#### Windows PowerShell

Install Python 3.12, Node.js 20 or newer, PostgreSQL, and Redis. No account is
needed for PostgreSQL or Redis when running them locally. Create a PostgreSQL
user and two databases matching the development values below:

```sql
CREATE USER auction WITH PASSWORD 'auction';
CREATE DATABASE auction_db OWNER auction;
CREATE DATABASE auction_test_db OWNER auction;
```

Then run the backend:

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
```

Edit `backend/.env` and use `localhost` for PostgreSQL and Redis (the example
file uses Docker service names):

```env
DATABASE_URL=postgresql+asyncpg://auction:auction@localhost:5432/auction_db
SYNC_DATABASE_URL=postgresql+psycopg2://auction:auction@localhost:5432/auction_db
REDIS_URL=redis://localhost:6379/0
```

Apply migrations and start the API:

```powershell
alembic upgrade head
uvicorn app.main:app --reload
```

In a second PowerShell terminal:

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

Open http://localhost:5173. The API documentation is available at
http://localhost:8000/docs.

#### Git Bash, WSL, or macOS/Linux

```bash
# Backend
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # edit DATABASE_URL/REDIS_URL to point at local services
alembic upgrade head
uvicorn app.main:app --reload   # also runs the worker in-process, see main.py

# Frontend (separate terminal)
cd frontend
npm ci
cp .env.example .env
npm run dev
```

You'll need local PostgreSQL and Redis reachable at the URLs in
`backend/.env`. Alternatively, `docker compose up postgres redis` can provide
those two services while the API and frontend run natively.

---

## Testing

```bash
# Backend unit tests (fast, SQLite, no external services needed)
cd backend
pytest tests/test_bid_validation.py tests/test_api_flows.py -v

# Backend concurrency + expiry tests (need a real Postgres reachable)
docker compose up -d postgres
TEST_DATABASE_URL=postgresql+asyncpg://auction:auction@localhost:5432/auction_test_db pytest -v

# Windows PowerShell equivalent
$env:TEST_DATABASE_URL = "postgresql+asyncpg://auction:auction@localhost:5432/auction_test_db"
pytest -v

# Frontend type-check + build
cd ../frontend
npm run type-check
npm run build

# Playwright e2e (needs the full stack running, e.g. via docker compose up)
npx playwright install
npm test
```

GitHub Actions (`.github/workflows/ci.yml`) runs the backend test suite
against real Postgres + Redis service containers on pushes and pull requests
targeting `main`, plus a
frontend type-check + build job.

The full Playwright test is intentionally separate from the default CI jobs:
it requires the complete API, worker, Redis, PostgreSQL, and frontend stack.

---

## Deliberately out of scope

Per the project brief, this intentionally does **not** include: Kafka,
Kubernetes, a microservices split, real payment processing, AI/ML
features, or a recommendation engine. The `Order` model exists to
represent "who owes what for which auction" but stops short of an actual
checkout/payment integration — that's a distinct problem with its own
concurrency/idempotency story and would roughly double the project's
surface area without teaching anything new about the core challenge
(concurrent bidding + realtime fan-out) this project is built to
demonstrate.

## Security and production notes

This is a portfolio and learning project, not a production deployment. Before
real use, replace the development JWT/database credentials, inject secrets
through the deployment environment, set `DEBUG=false`, restrict CORS, add
rate limiting, use HTTPS/WSS, and move browser authentication away from
`localStorage` if the threat model requires it. Payment, fulfilment, account
recovery, refresh-token revocation, and operational health checks are not
implemented.

Never commit `.env` files. The repository includes `.env.example` templates;
copy them locally and provide real values only in your local environment or a
secret manager.

## Things worth asking yourself before an interview

- Why `SELECT ... FOR UPDATE` instead of an optimistic `version` column
  compare-and-swap retry loop? (Answer sketch: both work; pessimistic is
  simpler to reason about and test for a write this hot/sensitive, at the
  cost of a bidder occasionally waiting a few ms behind another bidder on
  the *same* auction — a trade-off worth stating explicitly.)
- What happens if Redis is completely down? (Bids still work and are
  still correct — you only lose live push. Confirms Redis is not the
  source of truth.)
- What happens if two worker containers both try to finalize the same
  expired auction? (`SKIP LOCKED` — one wins, the other moves on to the
  next row instead of blocking or double-processing.)
- Why does `bid_service` re-validate `status`/time window even though the
  worker is supposed to flip status at the right time? (Defense in depth:
  the worker polls on an interval, so there's a window where an auction is
  logically over but the row hasn't been flipped yet — the bid's own
  timestamp check closes that gap.)
