import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auctions, auth, bids, users
from app.core.config import settings
from app.websocket.manager import connection_manager
from app.workers.auction_worker import run_forever

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

_worker_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _worker_task
    await connection_manager.connect()

    # The background worker runs in-process for local/dev/docker-compose
    # simplicity. In a multi-instance deployment you would run
    # `python -m app.workers.auction_worker` as its own container/process
    # instead (the docker-compose.yml in this project does exactly that -
    # see the `worker` service - and disables the in-process copy via
    # RUN_WORKER_IN_PROCESS=false) so the API and the worker scale
    # independently.
    if settings.ENV != "test" and _run_worker_in_process():
        _worker_task = asyncio.create_task(run_forever())

    yield

    if _worker_task:
        _worker_task.cancel()
    await connection_manager.disconnect()


def _run_worker_in_process() -> bool:
    import os

    return os.getenv("RUN_WORKER_IN_PROCESS", "true").lower() == "true"


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(auctions.router)
app.include_router(bids.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok"}
