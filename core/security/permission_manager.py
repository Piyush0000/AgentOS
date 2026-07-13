import re
import logging
from typing import Dict, Any, Tuple
from core.manifest.models import AgentManifest

logger = logging.getLogger("agentos.core.security")

class PermissionManager:
    @staticmethod
    def validate_tool_call(manifest: AgentManifest, tool_name: str, arguments: Dict[str, Any]) -> Tuple[bool, str]:
        """
        Validates tool execution against declarative manifest rules and security policies.
        Returns a tuple: (is_allowed, denial_reason_or_empty_string).
        """
        logger.info(f"Permission Manager inspecting tool_name={tool_name} with args={arguments}")

        # 1. Least Privilege Check: Verify tool is listed in manifest
        allowed_tool = None
        for t in manifest.tools:
            if t.name == tool_name:
                allowed_tool = t
                break

        if not allowed_tool:
            return False, f"Security Violation: Tool '{tool_name}' is not allowed in this agent's manifest."

        # 2. Advanced ABAC Rules by Tool Category
        if tool_name in ["file_read", "file_write"]:
            filepath = arguments.get("filepath", "")
            if not filepath:
                return False, "Error: filepath argument is missing."
                
            # Block directory traversal sequences
            if ".." in filepath or filepath.startswith("/") or filepath.startswith("\\") or ":" in filepath:
                return False, f"Security Violation: Directory traversal detected in path '{filepath}'."

        elif tool_name == "execute_command":
            command = arguments.get("command", "")
            if not command:
                return False, "Error: command argument is missing."

            # Block command injection patterns
            # Forbidden shell metacharacters
            forbidden_chars = [";", "&", "|", "`", "$", "\n", "\r", ">", "<"]
            if any(c in command for c in forbidden_chars):
                return False, "Security Violation: Command contains forbidden shell metacharacters (; & | ` $ > < or newlines)."

            # Forbidden commands
            # Parse tokens safely
            tokens = re.findall(r'\b\w+\b', command.lower())
            forbidden_commands = {
                "rm", "sudo", "env", "chmod", "chown", "kill", "wget", "curl", 
                "apt", "yum", "pip", "npm", "ssh", "sh", "bash", "powershell", "cmd"
            }
            
            intersect = forbidden_commands.intersection(tokens)
            if intersect:
                return False, f"Security Violation: Command utilizes forbidden system binaries: {list(intersect)}."

        elif tool_name == "calculate":
            expression = arguments.get("expression", "")
            if not expression:
                return False, "Error: expression argument is missing."
            
            # Restrict math calculator characters
            allowed_chars = set("0123456789+-*/(). ")
            if not set(expression).issubset(allowed_chars):
                return False, f"Security Violation: Math expression contains invalid characters."

        # Passed all validation checks
        return True, ""
