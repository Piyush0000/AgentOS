from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ToolPermission(BaseModel):
    name: str
    scopes: List[str] = Field(default_factory=list)  # e.g., ["read-only", "write"]

class MemoryConfig(BaseModel):
    context_window_limit: int = 16384
    semantic_retrieval_count: int = 5
    compression_enabled: bool = True

class BudgetConfig(BaseModel):
    max_tokens: int = 50000
    max_usd: float = 1.0

class AgentManifest(BaseModel):
    id: str  # Unique agent ID, e.g. "support-triage"
    name: str
    description: Optional[str] = None
    model: str = "gpt-4o"  # default model
    system_prompt: str
    tools: List[ToolPermission] = Field(default_factory=list)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    metadata: Dict[str, Any] = Field(default_factory=dict)
