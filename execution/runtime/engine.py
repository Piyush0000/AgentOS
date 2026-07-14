import json
import logging
from typing import Dict, Any, List
from sqlalchemy.orm import Session

from core.manifest.models import AgentManifest
from storage.database import TaskTable, AgentInstanceTable, CheckpointTable, ToolCallTable
from cognition.gateway.llm import LLMGateway
from memory.engine import MemoryEngine
from execution.sandbox.runner import ToolRunner
from core.security.permission_manager import PermissionManager

logger = logging.getLogger("agentos.execution.runtime")

class AgentRuntime:
    def __init__(self, llm_gateway: LLMGateway, memory_engine: MemoryEngine, tool_runner: ToolRunner):
        self.llm_gateway = llm_gateway
        self.memory_engine = memory_engine
        self.tool_runner = tool_runner
        self.max_loop_iterations = 15

    def execute_task(self, db: Session, task_id: str) -> Dict[str, Any]:
        """
        Executes a task from start to finish.
        Supports resume if a checkpoint already exists for the task.
        """
        # Fetch task and instance
        task = db.query(TaskTable).filter(TaskTable.id == task_id).first()
        if not task:
            raise ValueError(f"Task {task_id} not found.")

        instance = db.query(AgentInstanceTable).filter(AgentInstanceTable.id == task.instance_id).first()
        if not instance:
            raise ValueError(f"Agent instance for task {task_id} not found.")

        # Load Manifest
        # In a real system, manifest is fetched from the AgentRegistry. Here we parse it from the manifest registry / latest version
        from storage.database import AgentVersionTable
        latest_version = db.query(AgentVersionTable).filter(
            AgentVersionTable.manifest_id == instance.manifest_id,
            AgentVersionTable.version == instance.version
        ).first()
        
        if not latest_version:
            raise ValueError("Manifest version not found.")

        import yaml
        manifest_data = yaml.safe_load(latest_version.manifest_yaml)
        manifest = AgentManifest(**manifest_data)

        # Initialize State
        instance.status = "RUNNING"
        task.status = "RUNNING"
        db.commit()

        # Check for latest checkpoint to resume
        latest_checkpoint = db.query(CheckpointTable).filter(
            CheckpointTable.task_id == task_id
        ).order_by(CheckpointTable.step_index.desc()).first()

        step_index = 0
        working_memory = []

        if latest_checkpoint:
            logger.info(f"Resuming task {task_id} from checkpoint step {latest_checkpoint.step_index}")
            state_data = json.loads(latest_checkpoint.state_data)
            working_memory = state_data.get("working_memory", [])
            step_index = latest_checkpoint.step_index + 1
        else:
            # Set up initial prompt & context
            working_memory = [
                {"role": "system", "content": manifest.system_prompt},
                {"role": "user", "content": task.input_data}
            ]
            # Write initial checkpoint (step 0)
            self._save_checkpoint(db, task_id, 0, working_memory)
            step_index = 1

        # Format tools schema for LLM API
        llm_tools = self._get_llm_tools_schema(manifest)

        # Execution Loop
        try:
            total_tokens = 0
            while step_index <= self.max_loop_iterations:
                logger.info(f"Task {task_id} reasoning step {step_index}")
                
                # Apply working memory compression if needed
                active_context = self.memory_engine.get_working_memory(
                    working_memory, 
                    limit=manifest.memory.context_window_limit
                )

                # Read dynamic user credentials from task if populated
                provider = getattr(task, 'llm_provider', '')
                api_key = getattr(task, 'llm_api_key', '')

                # Inference call
                response = self.llm_gateway.generate_chat_completion(
                    model=manifest.model,
                    messages=active_context,
                    tools=llm_tools if llm_tools else None,
                    provider=provider if provider else None,
                    api_key=api_key if api_key else None
                )

                # Track token budget (simplified tracking for Milestone 1)
                # In mock mode or when token count is missing, we increment a mock value
                total_tokens += 1000
                if manifest.budget.max_tokens and total_tokens > manifest.budget.max_tokens:
                    raise ValueError(f"Token budget limit exceeded ({total_tokens} > {manifest.budget.max_tokens})")

                # Handle Text Content
                if response.content:
                    logger.info(f"Agent thought: {response.content}")
                    working_memory.append({"role": "assistant", "content": response.content})

                # Handle Tool Calls
                if response.tool_calls:
                    for tool_call in response.tool_calls:
                        tool_name = tool_call["name"]
                        args = tool_call["arguments"]
                        tc_id = tool_call["id"]

                        # Evaluate ABAC policy rules via PermissionManager
                        allowed, err_msg = PermissionManager.validate_tool_call(manifest, tool_name, args)
                        
                        # Audit Log: Record tool call request
                        audit_entry = ToolCallTable(
                            task_id=task_id,
                            tool_name=tool_name,
                            arguments=json.dumps(args),
                            status="ALLOWED" if allowed else "DENIED"
                        )
                        db.add(audit_entry)
                        db.commit()

                        if not allowed:
                            logger.warning(err_msg)
                            working_memory.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": tool_name,
                                "content": err_msg
                            })
                            audit_entry.result = err_msg
                            db.commit()
                            continue

                        # Execute in Sandbox
                        tool_result, is_success = self.tool_runner.execute_tool(task_id, tool_name, args)
                        
                        # Update Audit Log
                        audit_entry.result = tool_result
                        audit_entry.status = "SUCCESS" if is_success else "FAILED"
                        db.commit()

                        # Append tool results to working memory
                        working_memory.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": tool_name,
                            "content": tool_result
                        })

                    # Save Checkpoint after tool execution cycle
                    self._save_checkpoint(db, task_id, step_index, working_memory)
                    step_index += 1
                else:
                    # No tool calls: Agent returned final answer or completed thinking
                    task.status = "COMPLETED"
                    task.output_data = response.content
                    instance.status = "SLEEPING"
                    db.commit()
                    logger.info(f"Task {task_id} completed successfully.")
                    return {"task_id": task_id, "status": "COMPLETED", "output": response.content}

            # If loop finished without returning final answer
            raise TimeoutError(f"Task failed: Exceeded maximum iterations ({self.max_loop_iterations} turns).")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            task.status = "FAILED"
            task.error_message = str(e)
            instance.status = "SLEEPING"
            db.commit()
            return {"task_id": task_id, "status": "FAILED", "error": str(e)}

    def _save_checkpoint(self, db: Session, task_id: str, step_index: int, working_memory: List[Dict[str, Any]]):
        state_data = {
            "working_memory": working_memory
        }
        checkpoint = CheckpointTable(
            task_id=task_id,
            step_index=step_index,
            state_data=json.dumps(state_data)
        )
        db.add(checkpoint)
        db.commit()
        logger.info(f"Saved checkpoint for task {task_id} at step {step_index}")

    def _check_tool_permissions(self, manifest: AgentManifest, tool_name: str) -> bool:
        # Check if the tool is declared in manifest
        for tool_perm in manifest.tools:
            if tool_perm.name == tool_name:
                return True
        # For simplicity, if no tools listed in manifest, deny all tools by default (Least Privilege)
        return False

    def _get_llm_tools_schema(self, manifest: AgentManifest) -> List[Dict[str, Any]]:
        # Define the exact parameter schema of our supported tools for the LLM
        schema_map = {
            "file_write": {
                "name": "file_write",
                "description": "Writes text content to a file in the workspace directory. File will be created if it does not exist.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative path of file to write to"},
                        "content": {"type": "string", "description": "Text content to write"}
                    },
                    "required": ["filepath", "content"]
                }
            },
            "file_read": {
                "name": "file_read",
                "description": "Reads text content from a file in the workspace directory.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string", "description": "Relative path of file to read"}
                    },
                    "required": ["filepath"]
                }
            },
            "execute_command": {
                "name": "execute_command",
                "description": "Runs a shell command inside the workspace directory sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "The command string to execute"},
                        "timeout": {"type": "integer", "description": "Max execution time in seconds", "default": 30}
                    },
                    "required": ["command"]
                }
            },
            "calculate": {
                "name": "calculate",
                "description": "Performs basic mathematical operations (addition, subtraction, multiplication, division). Only basic numbers and math operations are allowed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "expression": {"type": "string", "description": "Mathematical expression to evaluate, e.g. '2 * 3.5'"}
                    },
                    "required": ["expression"]
                }
            }
        }
        
        allowed_tools = []
        for tool_perm in manifest.tools:
            if tool_perm.name in schema_map:
                allowed_tools.append(schema_map[tool_perm.name])
        return allowed_tools
