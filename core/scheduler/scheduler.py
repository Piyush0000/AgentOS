import logging
from sqlalchemy.orm import Session
from storage.database import TaskTable
from execution.runtime.engine import AgentRuntime

logger = logging.getLogger("agentos.core.scheduler")

class LocalScheduler:
    def __init__(self, runtime: AgentRuntime):
        self.runtime = runtime

    def schedule_next_task(self, db: Session) -> bool:
        """
        Looks for the next queued task sorted by priority (high > medium > low),
        and runs it synchronously using the AgentRuntime.
        Returns True if a task was processed, False otherwise.
        """
        # Load all queued tasks
        queued_tasks = db.query(TaskTable).filter(TaskTable.status == 'QUEUED').all()
        if not queued_tasks:
            return False

        # Sort tasks: high priority first, then medium, then low.
        priority_map = {'high': 3, 'medium': 2, 'low': 1}
        
        def get_priority_weight(task: TaskTable):
            return priority_map.get(task.priority.lower(), 2)

        # Sort by priority weight descending, then by creation date ascending
        queued_tasks.sort(key=lambda t: (-get_priority_weight(t), t.created_at))

        next_task = queued_tasks[0]
        logger.info(f"Scheduler selected task {next_task.id} (priority: {next_task.priority}) for execution.")
        
        # Execute the task
        self.runtime.execute_task(db, next_task.id)
        return True
