import logging
import asyncio
from sqlalchemy.orm import Session
from storage.database import SessionLocal, TaskTable
from core.event_bus import EventBus

logger = logging.getLogger("agentos.core.scheduler")

class LocalScheduler:
    """Milestone 1 compatible scheduler (sync)."""
    def __init__(self, runtime):
        self.runtime = runtime

    def schedule_next_task(self, db: Session) -> bool:
        queued_tasks = db.query(TaskTable).filter(TaskTable.status == 'QUEUED').all()
        if not queued_tasks:
            return False

        priority_map = {'high': 3, 'medium': 2, 'low': 1}
        def get_priority_weight(task: TaskTable):
            return priority_map.get(task.priority.lower(), 2)

        queued_tasks.sort(key=lambda t: (-get_priority_weight(t), t.created_at))
        next_task = queued_tasks[0]
        logger.info(f"Scheduler selected task {next_task.id} (priority: {next_task.priority}) for execution.")
        self.runtime.execute_task(db, next_task.id)
        return True

class SchedulerDaemon:
    """Milestone 2 Asynchronous Event-Driven Scheduler Daemon."""
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def start(self):
        logger.info("Starting Scheduler Daemon...")
        await self.event_bus.subscribe("tasks.queued", self.on_task_queued)
        logger.info("Scheduler Daemon subscribed to tasks.queued. Ready.")

    async def on_task_queued(self, data: dict):
        task_id = data.get("task_id")
        if not task_id:
            return
            
        logger.info(f"Scheduler Daemon received tasks.queued for task_id={task_id}")
        db = SessionLocal()
        try:
            task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
            if not task:
                logger.error(f"Task {task_id} not found in database.")
                return

            if task.status != "QUEUED":
                logger.warning(f"Task {task_id} has status {task.status}. Skipping scheduling.")
                return

            # Perform scheduling (Milestone 2: update task status and assign to node)
            task.status = "SCHEDULED"
            db.commit()
            logger.info(f"Scheduled task {task_id}. Emitting tasks.scheduled event.")
            
            # Emit tasks.scheduled event to NATS
            await self.event_bus.publish("tasks.scheduled", {
                "task_id": task_id,
                "instance_id": task.instance_id,
                "priority": task.priority
            })
            
        except Exception as e:
            logger.error(f"Error scheduling task {task_id}: {e}")
        finally:
            db.close()

async def main():
    import os
    logging.basicConfig(level=logging.INFO)
    nats_url = os.getenv("NATS_URL", "nats://localhost:4222")
    event_bus = EventBus(servers=[nats_url])
    await event_bus.connect()
    scheduler = SchedulerDaemon(event_bus)
    await scheduler.start()
    
    try:
        while True:
            await asyncio.sleep(3600)
    except KeyboardInterrupt:
        await event_bus.close()
        logger.info("Scheduler Daemon stopped.")

if __name__ == "__main__":
    asyncio.run(main())
