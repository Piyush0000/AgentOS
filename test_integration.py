import os
import sys
import yaml
import json
import logging
import time
import threading
import asyncio
import grpc
from fastapi.testclient import TestClient

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

# Import database, event bus, and schemas
from storage.database import init_db, SessionLocal, AgentManifestTable, AgentVersionTable, AgentInstanceTable, TaskTable, CheckpointTable, ToolCallTable
from core.event_bus import EventBus
from core.scheduler.scheduler import SchedulerDaemon
from execution.worker_daemon import WorkerDaemon
from api.server import app

# Import proto definitions
from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()

# Import gRPC Server serve functions
import cognition.server as cognition_server
import memory.server as memory_server
import core.registry.server as registry_server
import execution.runtime.server as runtime_server

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("agentos.test_integration")

def run_grpc_server(serve_fn):
    """Helper to run a gRPC server in a background thread."""
    try:
        serve_fn()
    except Exception as e:
        logger.error(f"gRPC server failed: {e}")

def run_integration_test():
    logger.info("Initializing AgentOS Distributed Integration Test...")
    
    # 1. Initialize Test Database (Drop and recreate tables cleanly to avoid Windows file locks)
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
    
    # 2. Start all 4 gRPC servers in background threads
    servers = [
        ("Cognition", cognition_server.serve),
        ("Memory", memory_server.serve),
        ("Registry", registry_server.serve),
        ("Runtime", runtime_server.serve)
    ]
    
    threads = []
    for name, serve_fn in servers:
        t = threading.Thread(target=run_grpc_server, args=(serve_fn,), daemon=True)
        t.start()
        threads.append(t)
        logger.info(f"Started background thread for {name} Plane gRPC Server.")
        
    # Wait for servers to bind
    time.sleep(2.0)
    
    # 3. Setup Async Event Loop in a separate thread for NATS Scheduler and Worker Daemons
    async_loop = asyncio.new_event_loop()
    
    def run_async_daemons(loop):
        asyncio.set_event_loop(loop)
        
        # Initialize EventBus
        event_bus = EventBus()
        loop.run_until_complete(event_bus.connect())
        
        # Start Scheduler Daemon
        scheduler = SchedulerDaemon(event_bus)
        loop.run_until_complete(scheduler.start())
        
        # Start Worker Daemon
        worker = WorkerDaemon(event_bus)
        loop.run_until_complete(worker.start())
        
        # Keep loop running
        loop.run_forever()
        
    daemon_thread = threading.Thread(target=run_async_daemons, args=(async_loop,), daemon=True)
    daemon_thread.start()
    logger.info("Started background thread for NATS Scheduler and Worker Daemons.")
    
    # Wait for daemons to initialize
    time.sleep(2.0)
    
    # 4. Use TestClient to send HTTP requests to API Gateway
    client = TestClient(app)
    
    # Verify root endpoint
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "online"
    
    # 5. Register Agent Manifest via API Gateway (routes to Registry Server over gRPC)
    logger.info("--- Phase 1: Register Agent Manifest ---")
    manifest_yaml = """
id: math-assistant
name: Mathematics AI Agent
description: Specialized mathematical solving agent.
model: gpt-4o
system_prompt: You are a math solver. When asked to evaluate expressions, always call the calculate tool.
tools:
  - name: calculate
    scopes: ["math"]
memory:
  context_window_limit: 8000
budget:
  max_tokens: 10000
  max_usd: 0.10
"""
    res_reg = client.post("/v1/agents", json={"manifest_yaml": manifest_yaml})
    assert res_reg.status_code == 200
    reg_data = res_reg.json()
    logger.info(f"Registered agent output: {reg_data}")
    assert reg_data["id"] == "math-assistant"
    assert reg_data["registered_version"] == 1
    
    # Get agent manifest verification
    res_get = client.get("/v1/agents/math-assistant")
    assert res_get.status_code == 200
    assert res_get.json()["latest_version"] == 1
    
    # 6. Submit Task 1: Authorized calculation task (events propagate through NATS)
    logger.info("--- Phase 2: Submit and Run Authorized Task ---")
    task_input = "Please calculate (25 * 4) + 12"
    res_task1 = client.post("/v1/agents/math-assistant/tasks", json={"input": task_input, "priority": "high"})
    assert res_task1.status_code == 200
    task1_data = res_task1.json()
    task1_id = task1_data["taskId"]
    logger.info(f"Submitted task 1: {task1_id}")
    
    # Wait for worker daemon to process the task through NATS and update DB status
    logger.info("Waiting for task execution to complete...")
    max_wait = 10
    task_status = "QUEUED"
    while max_wait > 0:
        time.sleep(1.0)
        res_status = client.get(f"/v1/tasks/{task1_id}")
        assert res_status.status_code == 200
        task_status = res_status.json()["status"]
        logger.info(f"Polling task status: {task_status}")
        if task_status in ["COMPLETED", "FAILED"]:
            break
        max_wait -= 1
        
    assert task_status == "COMPLETED", f"Task should have completed, got status: {task_status}"
    
    # Verify task 1 details from database
    db = SessionLocal()
    checkpoints = db.query(CheckpointTable).filter(CheckpointTable.task_id == task1_id).all()
    logger.info(f"Saved Checkpoints Count: {len(checkpoints)}")
    assert len(checkpoints) >= 2, "Task should have created at least 2 checkpoints (initial + after calculation)."
    
    tool_calls = db.query(ToolCallTable).filter(ToolCallTable.task_id == task1_id).all()
    logger.info(f"Audited Tool Calls Count: {len(tool_calls)}")
    assert len(tool_calls) == 1, "Task should have triggered exactly 1 calculation tool call."
    assert tool_calls[0].status == "SUCCESS"
    assert tool_calls[0].result == "112"
    
    # 7. Submit Task 2: Unauthorized Tool Call (Security Verification)
    logger.info("--- Phase 3: Submit and Run Unauthorized Task ---")
    
    # Dynamically inject the mock security threat into LLM gateway
    # Wait, the LLM Gateway is running inside the Cognition Server process.
    # Because it is in the same python interpreter (since we ran it on threads!), we can actually override
    # the method globally on the cognition server instance or set an env variable.
    # To test security, we can make the mock completion engine in llm.py trigger a security threat
    # if the prompt text contains 'unauthorized'.
    # Let's verify: in our _mock_call inside llm.py, does it handle any general mock call? Yes,
    # it returns 'Mock response'. If we submit a task with 'unauthorized', we can make the mock generator
    # request 'execute_command'.
    # Wait, let's write a small patch in test_integration.py that overrides GenerateCompletion in the cognition server.
    # We can fetch the running LLMGatewayService instance from gRPC if needed, or simply override
    # the method in LLMGateway before launching the servers!
    # Yes, we can patch LLMGateway.generate_chat_completion BEFORE starting the servers!
    # That is extremely clean.
    
    # Wait, let's verify if we need to mock it. In Phase 3, we want the LLM Gateway to output a security threat.
    # Let's look at the mock security threat override in Phase 3.
    # We can patch cognition_server's instance or the class method directly:
    from cognition.gateway.llm import LLMGateway
    original_generate = LLMGateway.generate_chat_completion
    
    def mock_security_threat_generation(self, model, messages, tools=None):
        # Check if the prompt is for security check
        last_msg = messages[-1]["content"] if messages else ""
        if "unauthorized" in last_msg.lower():
            has_tool_results = any(msg["role"] == "tool" for msg in messages)
            if has_tool_results:
                return type('LLMResponse', (object,), {
                    "content": "I cannot proceed because the system command execution was denied.",
                    "tool_calls": []
                })
            return type('LLMResponse', (object,), {
                "content": "I will execute a system command to inspect the directory.",
                "tool_calls": [{
                    "id": "call_malicious_cmd_002",
                    "name": "execute_command",
                    "arguments": {"command": "echo 'HACKED'"}
                }]
            })
        return original_generate(self, model, messages, tools)

    LLMGateway.generate_chat_completion = mock_security_threat_generation
    
    # Submit task 2 (unauthorized command request)
    res_task2 = client.post("/v1/agents/math-assistant/tasks", json={"input": "unauthorized command check"})
    assert res_task2.status_code == 200
    task2_id = res_task2.json()["taskId"]
    
    logger.info("Waiting for task 2 execution to complete...")
    max_wait = 10
    task2_status = "QUEUED"
    while max_wait > 0:
        time.sleep(1.0)
        res_status = client.get(f"/v1/tasks/{task2_id}")
        task2_status = res_status.json()["status"]
        logger.info(f"Polling task 2 status: {task2_status}")
        if task2_status in ["COMPLETED", "FAILED"]:
            break
        max_wait -= 1
        
    assert task2_status == "COMPLETED"
    
    # Verify tool execution audit log shows DENIED
    task2_tool_calls = db.query(ToolCallTable).filter(ToolCallTable.task_id == task2_id).all()
    logger.info(f"Audited Tool Calls Count for Task 2: {len(task2_tool_calls)}")
    assert len(task2_tool_calls) == 1, "Task 2 should have attempted exactly 1 tool call."
    assert task2_tool_calls[0].status == "DENIED"
    assert "Security Violation" in task2_tool_calls[0].result
    
    # 8. Semantic Memory integration (routes to Memory Server over gRPC)
    logger.info("--- Phase 4: Semantic Memory Insertion and Retrieval ---")
    client.post("/v1/memory/math-assistant/semantic", json={"text": "The standard mathematical constant pi is approximately 3.14159."})
    client.post("/v1/memory/math-assistant/semantic", json={"text": "Water boils at 100 degrees Celsius under standard atmospheric pressure."})
    client.post("/v1/memory/math-assistant/semantic", json={"text": "Pythagorean theorem states that a^2 + b^2 = c^2 for a right triangle."})
    
    # Search semantic memory
    res_search = client.get("/v1/memory/math-assistant/semantic", params={"query": "What theorem applies to right triangles?", "limit": 2})
    assert res_search.status_code == 200
    results = res_search.json()["results"]
    logger.info(f"Semantic search results: {results}")
    
    assert len(results) > 0
    assert "Pythagorean" in results[0]["text"], "Top search result should be the Pythagorean theorem."
    
    db.close()
    
    # Stop async loop
    async_loop.call_soon_threadsafe(async_loop.stop)
    logger.info("=============================================")
    logger.info("DISTRIBUTED INTEGRATION TESTS PASSED! ✅")
    logger.info("=============================================")

if __name__ == "__main__":
    run_integration_test()
