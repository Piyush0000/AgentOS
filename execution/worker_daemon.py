import os
import sys
import logging
import asyncio
import grpc

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()
from core.event_bus import EventBus

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentos.execution.worker_daemon")

class WorkerDaemon:
    def __init__(self, event_bus: EventBus, runtime_target="localhost:50054"):
        self.event_bus = event_bus
        self.runtime_target = runtime_target

    async def start(self):
        logger.info("Starting Worker Daemon...")
        await self.event_bus.subscribe("tasks.scheduled", self.on_task_scheduled)
        logger.info("Worker Daemon subscribed to tasks.scheduled. Ready.")

    async def on_task_scheduled(self, data: dict):
        task_id = data.get("task_id")
        if not task_id:
            return
            
        logger.info(f"Worker Daemon received tasks.scheduled event for task_id={task_id}")
        
        # Call Runtime gRPC Server to execute the task
        try:
            # We wrap the blocking gRPC call using asyncio.to_thread or run in executor to prevent blocking the event loop
            response = await asyncio.to_thread(self._grpc_execute_task, task_id)
            
            if response.status == "COMPLETED":
                logger.info(f"Task {task_id} executed successfully. Publishing tasks.completed.")
                await self.event_bus.publish("tasks.completed", {
                    "task_id": task_id,
                    "output": response.output
                })
            else:
                logger.error(f"Task {task_id} failed with error: {response.error}. Publishing tasks.failed.")
                await self.event_bus.publish("tasks.failed", {
                    "task_id": task_id,
                    "error": response.error
                })
        except Exception as e:
            logger.error(f"Failed to execute task {task_id} over gRPC: {e}")
            await self.event_bus.publish("tasks.failed", {
                "task_id": task_id,
                "error": f"Worker gRPC dispatch error: {str(e)}"
            })

    def _grpc_execute_task(self, task_id: str):
        with grpc.insecure_channel(self.runtime_target) as channel:
            stub = pb2_grpc.AgentRuntimeServiceStub(channel)
            request = pb2.ExecuteTaskRequest(task_id=task_id)
            return stub.ExecuteTask(request, timeout=300.0)  # Max 5 minute timeout per agent run

async def main():
    event_bus = EventBus()
    await event_bus.connect()
    worker = WorkerDaemon(event_bus)
    await worker.start()
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        await event_bus.close()
        logger.info("Worker Daemon stopped.")

if __name__ == "__main__":
    asyncio.run(main())
