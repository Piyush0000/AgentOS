import os
import sys
import yaml
import logging
import asyncio
from sqlalchemy.orm import Session

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("agentos.test_workflow")

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from storage.database import init_db, SessionLocal, AgentManifestTable, AgentVersionTable, AgentInstanceTable, TaskTable
from core.event_bus import EventBus
from core.workflow.engine import WorkflowEngine
from core.scheduler.scheduler import SchedulerDaemon
from execution.worker_daemon import WorkerDaemon
from cognition.gateway.llm import LLMGateway
from memory.engine import MemoryEngine
from execution.sandbox.runner import ToolRunner
from execution.runtime.engine import AgentRuntime

# Dynamic proto compilation
from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()

async def run_workflow_integration_test():
    logger.info("Initializing AgentOS Workflow Integration Test...")
    
    # 1. Clean Database (Drop and recreate tables cleanly to avoid Windows file locks)
    from storage.database import engine, Base
    try:
        Base.metadata.drop_all(bind=engine)
    except Exception as e:
        logger.warning(f"Could not drop all tables: {e}. Attempting file delete fallback.")
        if os.path.exists("agentos.db"):
            try:
                os.remove("agentos.db")
            except Exception as ex:
                logger.warning(f"Could not delete database file: {ex}. Proceeding with existing DB.")
    init_db()
    
    db: Session = SessionLocal()
    
    # 2. Register both manifests in database
    math_manifest_yaml = """
id: math-assistant
name: Math Solver Agent
description: Evaluates math expressions.
model: gpt-4o
system_prompt: You evaluate expressions.
tools:
  - name: calculate
"""
    summary_manifest_yaml = """
id: summary-agent
name: Summary Writer Agent
description: Summarizes inputs.
model: gpt-4o
system_prompt: You summarize outcomes.
tools: []
"""
    
    for manifest_yaml in [math_manifest_yaml, summary_manifest_yaml]:
        data = yaml.safe_load(manifest_yaml)
        manifest_record = AgentManifestTable(id=data["id"], name=data["name"], description=data["description"])
        db.add(manifest_record)
        
        version_record = AgentVersionTable(manifest_id=data["id"], version=1, manifest_yaml=manifest_yaml)
        db.add(version_record)
    db.commit()
    logger.info("Registered math-assistant and summary-agent manifests.")
    
    # 3. Create default instances
    for agent_id in ["math-assistant", "summary-agent"]:
        instance = AgentInstanceTable(manifest_id=agent_id, version=1, status="REGISTERED")
        db.add(instance)
    db.commit()
    db.close()
    
    # 4. Spin up mock gRPC server endpoints locally for the test
    # To keep the test programmatically self-contained without needing separate system terminals running,
    # we mock the direct gRPC Client Calls to call the runtime engine local instance directly.
    # We initialize the real components and bind NATS/EventBus together.
    
    event_bus = EventBus()
    await event_bus.connect()
    
    # Initialize execution runtime and scheduler daemons
    llm_gateway = LLMGateway()
    memory_engine = MemoryEngine(llm_gateway)
    tool_runner = ToolRunner()
    runtime = AgentRuntime(llm_gateway, memory_engine, tool_runner)
    
    # Scheduler Daemon
    scheduler_daemon = SchedulerDaemon(event_bus)
    await scheduler_daemon.start()
    
    # Mock gRPC execution inside worker by invoking runtime.execute_task directly on thread
    class DirectWorker(WorkerDaemon):
        async def on_task_scheduled(self, data: dict):
            task_id = data.get("task_id")
            logger.info(f"Test worker picked up task_id={task_id} from EventBus.")
            # Run task execution directly in DB
            db_session = SessionLocal()
            try:
                # Wrap execution to run on thread to simulate worker execution
                response = await asyncio.to_thread(runtime.execute_task, db_session, task_id)
                if response["status"] == "COMPLETED":
                    await self.event_bus.publish("tasks.completed", {
                        "task_id": task_id,
                        "output": response["output"]
                    })
                else:
                    await self.event_bus.publish("tasks.failed", {
                        "task_id": task_id,
                        "error": response.get("error", "Unknown error")
                    })
            except Exception as e:
                await self.event_bus.publish("tasks.failed", {"task_id": task_id, "error": str(e)})
            finally:
                db_session.close()

    worker_daemon = DirectWorker(event_bus)
    await worker_daemon.start()
    
    # 5. Define Workflow YAML (solve step -> summarize step)
    workflow_yaml = """
id: math-and-summary-dag
name: Calculation and Summarization Pipeline
steps:
  - id: solve
    agent_id: math-assistant
    input: "calculate (25 * 4) + 12"
    depends_on: []
  - id: summarize
    agent_id: summary-agent
    input: "summarize results: {solve.output}"
    depends_on: ["solve"]
"""
    
    # 6. Execute Workflow Engine
    workflow_engine = WorkflowEngine(event_bus)
    logger.info("Executing Workflow DAG...")
    
    result = await workflow_engine.execute_workflow(workflow_yaml, initial_context={"user": "tets_user"})
    
    logger.info("--- Workflow Execution Results ---")
    logger.info(f"Workflow final status: {result['status']}")
    logger.info(f"Outputs mapping: {result['outputs']}")
    logger.info(f"Step status mapping: {result['step_status']}")
    
    # Assertions
    assert result["status"] == "COMPLETED", "Workflow failed to complete."
    assert result["step_status"]["solve"] == "COMPLETED", "Solve step did not complete."
    assert result["step_status"]["summarize"] == "COMPLETED", "Summarize step did not complete."
    assert "112" in result["outputs"]["solve"], "Calculation results missing from outputs."
    assert "112" in result["outputs"]["summarize"], "Summarized output did not capture solve results."
    
    await event_bus.close()
    logger.info("==========================================")
    logger.info("WORKFLOW ENGINE INTEGRATION TEST PASSED! ✅")
    logger.info("==========================================")

if __name__ == "__main__":
    asyncio.run(run_workflow_integration_test())
