import json
import asyncio
import logging
from typing import Dict, Any, Callable, Awaitable

logger = logging.getLogger("agentos.core.event_bus")

class EventBus:
    # Class-level shared broker handlers: subject -> list of (async callback, registering event loop)
    in_memory_handlers = {}

    def __init__(self, servers=None):
        if servers is None:
            servers = ["nats://localhost:4222"]
        self.servers = servers
        self.nc = None
        self.connected = False

    async def connect(self):
        try:
            from nats.aio.client import Client as NATS
            self.nc = NATS()
            await self.nc.connect(
                servers=self.servers, 
                connect_timeout=0.5, 
                allow_reconnect=False, 
                max_reconnect_attempts=0
            )
            self.connected = True
            logger.info("Successfully connected to NATS Server. ✅")
        except Exception as e:
            logger.warning(f"Could not connect to NATS: {e}. Falling back to in-memory Event Bus.")
            self.connected = False
            self.nc = None

    async def publish(self, subject: str, data: Dict[str, Any]):
        payload = json.dumps(data).encode('utf-8')
        if self.connected and self.nc:
            await self.nc.publish(subject, payload)
            logger.info(f"[NATS Publish] subject={subject} data={data}")
        else:
            logger.info(f"[In-Memory Publish] subject={subject} data={data}")
            # Trigger mock subscriptions
            if subject in EventBus.in_memory_handlers:
                for handler, loop in EventBus.in_memory_handlers[subject]:
                    try:
                        if loop and loop.is_running():
                            # Safely schedule across thread loops
                            asyncio.run_coroutine_threadsafe(handler(data), loop)
                        else:
                            # Run on current event loop
                            asyncio.create_task(handler(data))
                    except Exception as ex:
                        logger.error(f"Error dispatching in-memory handler: {ex}")

    async def subscribe(self, subject: str, handler: Callable[[Dict[str, Any]], Awaitable[None]]):
        if self.connected and self.nc:
            async def nats_callback(msg):
                try:
                    data = json.loads(msg.data.decode('utf-8'))
                    await handler(data)
                except Exception as ex:
                    logger.error(f"Error handling NATS message: {ex}")
            await self.nc.subscribe(subject, cb=nats_callback)
            logger.info(f"[NATS Subscribe] Subscribed to subject={subject}")
        else:
            # Capture the current thread's active event loop
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
                
            if subject not in EventBus.in_memory_handlers:
                EventBus.in_memory_handlers[subject] = []
            EventBus.in_memory_handlers[subject].append((handler, loop))
            logger.info(f"[In-Memory Subscribe] Subscribed to subject={subject}")

    async def close(self):
        if self.connected and self.nc:
            await self.nc.close()
            logger.info("NATS connection closed.")
