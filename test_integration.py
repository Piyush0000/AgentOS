import os
import sys
import yaml
import logging
from sqlalchemy.orm import Session

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("agentos.test_integration")

# Import AgentOS modules
from storage.database import init_db, SessionLocal, AgentManifestTable, AgentVersionTable, AgentInstanceTable, TaskTable, CheckpointTable, ToolCallTable, SemanticMemoryTable
from core.manifest.models import AgentManifest
from cognition.gateway.llm import LLMGateway
from memory.engine import MemoryEngine
from execution.sandbox.runner import ToolRunner
from execution.runtime.engine import AgentRuntime
from core.scheduler.scheduler import LocalScheduler

def run_integration_test():
    logger.info("Initializing AgentOS Integration Test...")
    
    # 1. Initialize Test SQLite Database
    if os.path.exists("agentos.db"):
        os.remove("agentos.db")
    init_db()
    
    db: Session = SessionLocal()
    
    # 2. Define Agent Manifest YAML (Only allows 'calculate' tool, denies others)
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
    
    logger.info("--- Phase 1: Register Agent Manifest ---")
    manifest_data = yaml.safe_load(manifest_yaml)
    manifest = AgentManifest(**manifest_data)
    
    # Write manifest to DB
    manifest_record = AgentManifestTable(
        id=manifest.id,
        name=manifest.name,
        description=manifest.description
    )
    db.add(manifest_record)
    db.commit()
    
    version_record = AgentVersionTable(
        manifest_id=manifest.id,
        version=1,
        manifest_yaml=manifest_yaml
    )
    db.add(version_record)
    db.commit()
    logger.info(f"Registered agent '{manifest.id}' version 1.")
    
    # 3. Create Agent Instance
    instance = AgentInstanceTable(
        manifest_id=manifest.id,
        version=1,
        status="REGISTERED"
    )
    db.add(instance)
    db.commit()
    logger.info(f"Created agent instance: {instance.id}")
    
    # 4. Initialize Subsystems
    llm_gateway = LLMGateway()
    memory_engine = MemoryEngine(llm_gateway)
    tool_runner = ToolRunner()
    runtime = AgentRuntime(llm_gateway, memory_engine, tool_runner)
    scheduler = LocalScheduler(runtime)
    
    # 5. Submit Task 1: Authorized Tool Call (Math Expression Evaluation)
    logger.info("--- Phase 2: Submit and Run Authorized Task ---")
    task_input = "Please calculate (25 * 4) + 12"
    task1 = TaskTable(
        instance_id=instance.id,
        input_data=task_input,
        status="QUEUED",
        priority="high"
    )
    db.add(task1)
    db.commit()
    logger.info(f"Enqueued task 1: {task1.id} (Input: '{task_input}')")
    
    # Trigger scheduler
    logger.info("Triggering scheduler loop to process task 1...")
    scheduled = scheduler.schedule_next_task(db)
    assert scheduled is True, "Scheduler failed to pick up the queued task."
    
    # Refresh task 1 state from DB
    db.refresh(task1)
    logger.info(f"Task 1 status: {task1.status}")
    logger.info(f"Task 1 final output: {task1.output_data}")
    
    # Verify execution details in Database
    checkpoints = db.query(CheckpointTable).filter(CheckpointTable.task_id == task1.id).all()
    logger.info(f"Saved Checkpoints Count for Task 1: {len(checkpoints)}")
    assert len(checkpoints) >= 2, "Task should have created at least 2 checkpoints (initial state + after tool execution)."
    
    tool_calls = db.query(ToolCallTable).filter(ToolCallTable.task_id == task1.id).all()
    logger.info(f"Audited Tool Calls Count for Task 1: {len(tool_calls)}")
    assert len(tool_calls) == 1, "Task should have triggered exactly 1 tool call."
    logger.info(f"Audited Tool: {tool_calls[0].tool_name}, Status: {tool_calls[0].status}, Result: {tool_calls[0].result}")
    assert tool_calls[0].status == "SUCCESS", "Math calculation tool call should have succeeded."
    assert tool_calls[0].result == "112", f"Expected calculation result '112', got '{tool_calls[0].result}'."
    
    # 6. Submit Task 2: Unauthorized Tool Call (Security / Policy Check)
    logger.info("--- Phase 3: Submit and Run Unauthorized Task ---")
    # We will submit a task designed to trigger a tool call not allowed in the manifest.
    # In order to trigger it in mock LLM mode, we customize the mock inference to request 'execute_command'
    # if the query contains 'execute'.
    # Let's override LLM gateway response for testing this security constraint.
    original_generate = llm_gateway.generate_chat_completion
    
    def mock_security_threat_generation(model, messages, tools=None):
        has_tool_results = any(msg["role"] == "tool" for msg in messages)
        if has_tool_results:
            return type('LLMResponse', (object,), {
                "content": "I cannot proceed because the system command execution was denied.",
                "tool_calls": []
            })
        # Return a response that calls an unauthorized tool 'execute_command'
        return type('LLMResponse', (object,), {
            "content": "I will execute a system command to inspect the directory.",
            "tool_calls": [{
                "id": "call_malicious_cmd_001",
                "name": "execute_command",
                "arguments": {"command": "echo 'HACKED'"}
            }]
        })
        
    llm_gateway.generate_chat_completion = mock_security_threat_generation
    
    task2_input = "Attempt to run execute_command"
    task2 = TaskTable(
        instance_id=instance.id,
        input_data=task2_input,
        status="QUEUED",
        priority="medium"
    )
    db.add(task2)
    db.commit()
    logger.info(f"Enqueued task 2: {task2.id} (Input: '{task2_input}')")
    
    # Run task 2 via scheduler
    scheduler.schedule_next_task(db)
    
    db.refresh(task2)
    logger.info(f"Task 2 final status: {task2.status}")
    
    # Verify tool execution audit log shows DENIED
    task2_tool_calls = db.query(ToolCallTable).filter(ToolCallTable.task_id == task2.id).all()
    logger.info(f"Audited Tool Calls Count for Task 2: {len(task2_tool_calls)}")
    assert len(task2_tool_calls) == 1, "Task 2 should have attempted 1 tool call."
    logger.info(f"Audited Tool Call Status: {task2_tool_calls[0].status}, Result: {task2_tool_calls[0].result}")
    assert task2_tool_calls[0].status == "DENIED", "Security policy should have DENIED the execute_command tool call."
    assert "Security Violation" in task2_tool_calls[0].result, "Audit log should state that execution was denied."
    
    # Restore original method
    llm_gateway.generate_chat_completion = original_generate
    
    # 7. Semantic Memory Integration Test
    logger.info("--- Phase 4: Semantic Memory Insertion and Retrieval ---")
    memory_engine.save_semantic_memory(db, manifest.id, "The standard mathematical constant pi is approximately 3.14159.")
    memory_engine.save_semantic_memory(db, manifest.id, "Water boils at 100 degrees Celsius under standard atmospheric pressure.")
    memory_engine.save_semantic_memory(db, manifest.id, "Pythagorean theorem states that a^2 + b^2 = c^2 for a right triangle.")
    
    # Retrieve memories relating to math
    search_query = "What theorem applies to right triangles?"
    results = memory_engine.search_semantic_memory(db, manifest.id, search_query, limit=2)
    logger.info(f"Semantic search query: '{search_query}'")
    logger.info(f"Found {len(results)} results:")
    for idx, r in enumerate(results):
        logger.info(f"Result {idx+1}: '{r['text']}' (Similarity score: {r['similarity']:.4f})")
        
    assert len(results) > 0, "Semantic memory search should return results."
    assert "Pythagorean" in results[0]["text"], "Top search result should be the Pythagorean theorem."
    
    db.close()
    logger.info("=============================================")
    logger.info("ALL INTEGRATION TESTS PASSED SUCCESSFULLY! ✅")
    logger.info("=============================================")

if __name__ == "__main__":
    run_integration_test()
