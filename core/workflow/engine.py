import yaml
import logging
import asyncio
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from storage.database import SessionLocal, TaskTable, AgentInstanceTable, AgentVersionTable
from core.event_bus import EventBus

logger = logging.getLogger("agentos.core.workflow")

class WorkflowEngine:
    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def execute_workflow(self, workflow_yaml: str, initial_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parses the workflow YAML, creates a dependency DAG, and executes the steps
        in order of their dependencies by publishing NATS events.
        """
        # Parse YAML
        try:
            workflow_def = yaml.safe_load(workflow_yaml)
        except Exception as e:
            return {"status": "FAILED", "error": f"Invalid workflow YAML: {e}"}

        workflow_id = workflow_def.get("id", "workflow")
        steps = workflow_def.get("steps", [])
        logger.info(f"Starting workflow '{workflow_id}' with {len(steps)} steps.")

        # Keep track of states
        # step_id -> status ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')
        step_status = {step["id"]: "PENDING" for step in steps}
        step_outputs = {}
        task_id_to_step_id = {}
        
        # Create map of steps
        step_map = {step["id"]: step for step in steps}

        # Keep running list of tasks we are currently waiting for
        active_tasks = {}  # task_id -> step_id

        # Async event to signal task completion
        task_completed_event = asyncio.Event()

        # Define internal handler for NATS task status updates
        async def on_task_completed(data: dict):
            t_id = data.get("task_id")
            if t_id in active_tasks:
                s_id = active_tasks[t_id]
                logger.info(f"Workflow step '{s_id}' completed with task_id={t_id}")
                step_status[s_id] = "COMPLETED"
                step_outputs[s_id] = data.get("output", "")
                del active_tasks[t_id]
                task_completed_event.set()

        async def on_task_failed(data: dict):
            t_id = data.get("task_id")
            if t_id in active_tasks:
                s_id = active_tasks[t_id]
                logger.error(f"Workflow step '{s_id}' failed with task_id={t_id}")
                step_status[s_id] = "FAILED"
                del active_tasks[t_id]
                task_completed_event.set()

        # Subscribe to NATS events
        await self.event_bus.subscribe("tasks.completed", on_task_completed)
        await self.event_bus.subscribe("tasks.failed", on_task_failed)

        # Loop until all steps are done or one has failed
        while True:
            # Check if any step failed
            if any(status == "FAILED" for status in step_status.values()):
                logger.error(f"Workflow '{workflow_id}' failed due to step failures.")
                return {"status": "FAILED", "outputs": step_outputs, "step_status": step_status}

            # Check if all steps completed
            if all(status == "COMPLETED" for status in step_status.values()):
                logger.info(f"Workflow '{workflow_id}' completed successfully! 🎉")
                return {"status": "COMPLETED", "outputs": step_outputs, "step_status": step_status}

            # Find steps that are PENDING and have all dependencies met
            triggered_any = False
            for step_id, status in step_status.items():
                if status != "PENDING":
                    continue

                step = step_map[step_id]
                deps = step.get("depends_on", [])
                
                # Check if all dependencies are COMPLETED
                if all(step_status.get(dep_id) == "COMPLETED" for dep_id in deps):
                    logger.info(f"Triggering workflow step '{step_id}'...")
                    
                    # Resolve input variable bindings, e.g. {classify.output}
                    resolved_input = self._resolve_variables(step.get("input", ""), initial_context, step_outputs)
                    
                    # Enqueue task in DB
                    task_id = self._create_db_task(step["agent_id"], resolved_input)
                    
                    # Track task in workflow state
                    step_status[step_id] = "RUNNING"
                    active_tasks[task_id] = step_id
                    triggered_any = True
                    
                    # Publish event to start task
                    await self.event_bus.publish("tasks.queued", {"task_id": task_id})

            if triggered_any:
                # Reset task event and wait for next task status change
                task_completed_event.clear()

            # Wait for any running task to complete
            if active_tasks:
                await task_completed_event.wait()
                task_completed_event.clear()
            elif not triggered_any:
                # No tasks are running, and no new tasks can be scheduled. Deadlock or cycles!
                err_msg = "Workflow deadlock detected: Check for cyclic dependencies in workflow steps."
                logger.error(err_msg)
                return {"status": "FAILED", "error": err_msg}

    def _resolve_variables(self, input_template: str, context: dict, step_outputs: dict) -> str:
        """Replaces bindings like {context_var} or {step_id.output} with values."""
        resolved = input_template
        
        # Match variables from context
        for k, v in context.items():
            resolved = resolved.replace(f"{{{k}}}", str(v))
            
        # Match variables from step outputs
        for step_id, output in step_outputs.items():
            resolved = resolved.replace(f"{{{step_id}.output}}", str(output))
            
        return resolved

    def _create_db_task(self, agent_id: str, input_data: str) -> str:
        db = SessionLocal()
        try:
            # Get latest version
            latest_version = db.query(AgentVersionTable).filter(
                AgentVersionTable.manifest_id == agent_id
            ).order_by(AgentVersionTable.version.desc()).first()
            
            if not latest_version:
                raise ValueError(f"Agent manifest '{agent_id}' not found.")

            # Get default instance
            instance = db.query(AgentInstanceTable).filter(
                AgentInstanceTable.manifest_id == agent_id,
                AgentInstanceTable.version == latest_version.version
            ).first()
            
            if not instance:
                instance = AgentInstanceTable(
                    manifest_id=agent_id,
                    version=latest_version.version,
                    status="REGISTERED"
                )
                db.add(instance)
                db.commit()

            # Create task
            task = TaskTable(
                instance_id=instance.id,
                input_data=input_data,
                status="QUEUED"
            )
            db.add(task)
            db.commit()
            
            return task.id
        finally:
            db.close()
