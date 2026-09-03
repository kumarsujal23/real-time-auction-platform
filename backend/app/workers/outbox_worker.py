import asyncio
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import AsyncSessionLocal
from app.models.outbox import OutboxEvent
from app.websocket.manager import connection_manager

logger = logging.getLogger(__name__)

async def process_outbox_events() -> None:
    while True:
        try:
            async with AsyncSessionLocal() as db:
                stmt = select(OutboxEvent).with_for_update(skip_locked=True).limit(100)
                events = (await db.execute(stmt)).scalars().all()
                if not events:
                    await asyncio.sleep(0.5)
                    continue

                for event in events:
                    try:
                        await connection_manager.publish(event.topic, event.payload)
                        await db.delete(event)
                    except Exception as e:
                        logger.error(f"Failed to publish outbox event {event.id}: {e}")

                await db.commit()
        except Exception as e:
            logger.error(f"Outbox worker error: {e}")
            await asyncio.sleep(1)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(process_outbox_events())
