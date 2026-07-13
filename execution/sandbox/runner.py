import os
import shutil
import subprocess
import logging
import json
from typing import Dict, Any, Tuple

logger = logging.getLogger("agentos.execution.sandbox")

class ToolRunner:
    def __init__(self, base_sandbox_dir: str = "./scratch"):
        self.base_sandbox_dir = os.path.abspath(base_sandbox_dir)
        os.makedirs(self.base_sandbox_dir, exist_ok=True)
        self.use_docker = False
        self.docker_client = None
        self._init_docker()

    def _init_docker(self):
        try:
            import docker
            self.docker_client = docker.from_env()
            self.docker_client.ping()
            self.use_docker = True
            logger.info("Successfully connected to local Docker daemon. Sandbox container execution enabled. 🐳")
        except Exception as e:
            logger.warning(f"Docker not available: {e}. Falling back to local subprocess sandbox.")
            self.use_docker = False
            self.docker_client = None

    def _get_task_dir(self, task_id: str) -> str:
        task_dir = os.path.join(self.base_sandbox_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        return task_dir

    def execute_tool(self, task_id: str, tool_name: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        """
        Executes a tool and returns a tuple (result_string, is_success).
        All file operations are isolated to the task's directory.
        """
        task_dir = self._get_task_dir(task_id)
        logger.info(f"Executing tool {tool_name} for task {task_id} in sandbox {task_dir}")

        try:
            if tool_name == "file_write":
                return self._tool_file_write(task_dir, arguments)
            elif tool_name == "file_read":
                return self._tool_file_read(task_dir, arguments)
            elif tool_name == "execute_command":
                return self._tool_execute_command(task_dir, arguments)
            elif tool_name == "calculate":
                return self._tool_calculate(arguments)
            else:
                return f"Error: Unknown tool '{tool_name}'", False
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            return f"Error executing tool: {str(e)}", False

    def _tool_file_write(self, task_dir: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        filepath = arguments.get("filepath")
        content = arguments.get("content", "")
        if not filepath:
            return "Error: filepath argument is required", False

        # Prevent directory traversal
        safe_path = os.path.abspath(os.path.join(task_dir, filepath))
        if not safe_path.startswith(task_dir):
            return "Error: Security violation - attempting to write outside the sandbox directory", False

        os.makedirs(os.path.dirname(safe_path), exist_ok=True)
        with open(safe_path, "w", encoding="utf-8") as f:
            f.write(content)

        return f"Successfully wrote to file: {filepath}", True

    def _tool_file_read(self, task_dir: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        filepath = arguments.get("filepath")
        if not filepath:
            return "Error: filepath argument is required", False

        # Prevent directory traversal
        safe_path = os.path.abspath(os.path.join(task_dir, filepath))
        if not safe_path.startswith(task_dir):
            return "Error: Security violation - attempting to read outside the sandbox directory", False

        if not os.path.exists(safe_path):
            return f"Error: File not found: {filepath}", False

        with open(safe_path, "r", encoding="utf-8") as f:
            content = f.read()

        return content, True

    def _tool_execute_command(self, task_dir: str, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        command = arguments.get("command")
        timeout = arguments.get("timeout", 30)
        if not command:
            return "Error: command argument is required", False

        if self.use_docker and self.docker_client:
            logger.info(f"Running command inside Docker container: {command}")
            try:
                # Mount task scratch directory to /workspace in python:3.10-alpine
                container = self.docker_client.containers.run(
                    image="python:3.10-alpine",
                    command=f"sh -c {json.dumps(command)}",
                    volumes={task_dir: {"bind": "/workspace", "mode": "rw"}},
                    working_dir="/workspace",
                    network_mode="none",   # Disable container internet/network access
                    mem_limit="256m",      # RAM limit
                    nano_cpus=1000000000,  # 1 CPU limit
                    detach=True
                )
                
                try:
                    res = container.wait(timeout=timeout)
                    exit_code = res.get("StatusCode", 0)
                    logs = container.logs(stdout=True, stderr=True).decode("utf-8")
                    is_success = (exit_code == 0)
                    output = f"EXIT CODE: {exit_code}\nLOGS:\n{logs}"
                    return output, is_success
                except Exception as wait_ex:
                    logger.error(f"Container execution timed out: {wait_ex}")
                    try:
                        container.kill()
                    except Exception:
                        pass
                    return f"Error: Command timed out after {timeout} seconds inside sandbox container.", False
                finally:
                    try:
                        container.remove()
                    except Exception:
                        pass
            except Exception as docker_ex:
                logger.warning(f"Docker run failed: {docker_ex}. Falling back to local subprocess.")

        # Fallback to local subprocess runner
        logger.info(f"Running command inside local subprocess: {command}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=task_dir,
                text=True,
                capture_output=True,
                timeout=timeout
            )
            
            output = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            is_success = (result.returncode == 0)
            return output, is_success
        except subprocess.TimeoutExpired:
            return f"Error: Command timed out after {timeout} seconds.", False
        except Exception as e:
            return f"Error executing shell command: {str(e)}", False

    def _tool_calculate(self, arguments: Dict[str, Any]) -> Tuple[str, bool]:
        expression = arguments.get("expression")
        if not expression:
            return "Error: expression argument is required", False
            
        try:
            allowed_chars = "0123456789+-*/(). "
            if any(c not in allowed_chars for c in expression):
                return "Error: Invalid characters in expression", False
                
            val = eval(expression, {"__builtins__": None}, {})
            return str(val), True
        except Exception as e:
            return f"Error evaluating expression: {str(e)}", False

    def clean_sandbox(self, task_id: str):
        """Clean up sandbox files for a completed task."""
        task_dir = os.path.join(self.base_sandbox_dir, task_id)
        if os.path.exists(task_dir):
            shutil.rmtree(task_dir)
            logger.info(f"Cleaned sandbox directory: {task_dir}")
