import os
import yaml
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from storage.database import init_db, get_db, AgentManifestTable, AgentVersionTable, AgentInstanceTable, TaskTable, CheckpointTable, ToolCallTable
from core.manifest.models import AgentManifest
from cognition.gateway.llm import LLMGateway
from memory.engine import MemoryEngine
from execution.sandbox.runner import ToolRunner
from execution.runtime.engine import AgentRuntime
from core.scheduler.scheduler import LocalScheduler

# Initialize database on startup
init_db()

app = FastAPI(
    title="AgentOS API Gateway", 
    description="The Operating System for Autonomous AI Agents - Milestone 1",
    version="1.0"
)

# Initialize subsystems
llm_gateway = LLMGateway()
memory_engine = MemoryEngine(llm_gateway)
tool_runner = ToolRunner()
runtime = AgentRuntime(llm_gateway, memory_engine, tool_runner)
scheduler = LocalScheduler(runtime)

# Request validation schemas
class RegisterAgentRequest(BaseModel):
    manifest_yaml: str

class SubmitTaskRequest(BaseModel):
    input: str
    priority: str = "medium"  # low, medium, high
    max_tokens: Optional[int] = 50000
    max_usd: Optional[float] = 1.0

class SemanticMemoryAddRequest(BaseModel):
    text: str

# Helper to run scheduler in background
def run_scheduler_background():
    db = next(get_db())
    try:
        scheduler.schedule_next_task(db)
    finally:
        db.close()


@app.get("/")
def read_root():
    return {
        "status": "online",
        "system": "AgentOS",
        "version": "1.0-milestone1",
        "subsystems": {
            "llm_gateway": "ready",
            "memory_engine": "ready",
            "tool_runner": "ready",
            "scheduler": "ready"
        }
    }


# --- Agent Registration ---
@app.post("/v1/agents")
def register_agent(req: RegisterAgentRequest, db: Session = Depends(get_db)):
    try:
        manifest_data = yaml.safe_load(req.manifest_yaml)
        manifest = AgentManifest(**manifest_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid manifest YAML: {str(e)}")

    # Check if manifest already exists
    manifest_record = db.query(AgentManifestTable).filter(AgentManifestTable.id == manifest.id).first()
    if not manifest_record:
        manifest_record = AgentManifestTable(
            id=manifest.id,
            name=manifest.name,
            description=manifest.description
        )
        db.add(manifest_record)
        db.commit()

    # Create next version
    latest_version = db.query(AgentVersionTable).filter(
        AgentVersionTable.manifest_id == manifest.id
    ).order_by(AgentVersionTable.version.desc()).first()
    
    next_ver = (latest_version.version + 1) if latest_version else 1
    
    version_record = AgentVersionTable(
        manifest_id=manifest.id,
        version=next_ver,
        manifest_yaml=req.manifest_yaml
    )
    db.add(version_record)
    db.commit()

    return {
        "id": manifest.id,
        "name": manifest.name,
        "registered_version": next_ver,
        "status": "success"
    }


@app.get("/v1/agents/{id}")
def get_agent_manifest(id: str, db: Session = Depends(get_db)):
    manifest_record = db.query(AgentManifestTable).filter(AgentManifestTable.id == id).first()
    if not manifest_record:
        raise HTTPException(status_code=404, detail="Agent manifest not found")

    latest_version = db.query(AgentVersionTable).filter(
        AgentVersionTable.manifest_id == id
    ).order_by(AgentVersionTable.version.desc()).first()

    return {
        "id": manifest_record.id,
        "name": manifest_record.name,
        "description": manifest_record.description,
        "latest_version": latest_version.version if latest_version else None,
        "manifest_yaml": latest_version.manifest_yaml if latest_version else None
    }


# --- Task Submission & Scheduling ---
@app.post("/v1/agents/{id}/tasks")
def submit_task(
    id: str, 
    req: SubmitTaskRequest, 
    background_tasks: BackgroundTasks, 
    db: Session = Depends(get_db)
):
    # Verify manifest exists
    latest_version = db.query(AgentVersionTable).filter(
        AgentVersionTable.manifest_id == id
    ).order_by(AgentVersionTable.version.desc()).first()
    
    if not latest_version:
        raise HTTPException(status_code=404, detail="Agent manifest not found")

    # For Milestone 1, auto-create a default instance of this agent if none exists
    instance = db.query(AgentInstanceTable).filter(
        AgentInstanceTable.manifest_id == id,
        AgentInstanceTable.version == latest_version.version
    ).first()
    
    if not instance:
        instance = AgentInstanceTable(
            manifest_id=id,
            version=latest_version.version,
            status="REGISTERED"
        )
        db.add(instance)
        db.commit()

    # Create task
    task = TaskTable(
        instance_id=instance.id,
        input_data=req.input,
        status="QUEUED",
        priority=req.priority,
        max_tokens=req.max_tokens,
        max_usd=req.max_usd
    )
    db.add(task)
    db.commit()

    # Trigger scheduler run in background
    background_tasks.add_task(run_scheduler_background)

    return {
        "taskId": task.id,
        "instanceId": instance.id,
        "status": "queued",
        "priority": task.priority,
        "streamUrl": f"ws://localhost:8000/v1/tasks/{task.id}/stream"
    }


@app.get("/v1/tasks/{id}")
def get_task_status(id: str, db: Session = Depends(get_db)):
    task = db.query(TaskTable).filter(TaskTable.id == id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Get checkpoints count
    checkpoints_count = db.query(CheckpointTable).filter(CheckpointTable.task_id == id).count()

    # Get tool calls audits
    tool_calls = db.query(ToolCallTable).filter(ToolCallTable.task_id == id).all()
    audits = [{
        "tool": tc.tool_name,
        "status": tc.status,
        "created_at": tc.created_at
    } for tc in tool_calls]

    return {
        "taskId": task.id,
        "status": task.status,
        "input": task.input_data,
        "output": task.output_data,
        "error": task.error_message,
        "checkpoints_count": checkpoints_count,
        "audited_tool_calls": audits,
        "created_at": task.created_at,
        "updated_at": task.updated_at
    }


# --- Semantic Memory Operations ---
@app.post("/v1/memory/{agent_id}/semantic")
def add_semantic_memory(agent_id: str, req: SemanticMemoryAddRequest, db: Session = Depends(get_db)):
    try:
        memory_engine.save_semantic_memory(db, agent_id, req.text)
        return {"status": "success", "message": "Semantic memory stored."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/memory/{agent_id}/semantic")
def search_semantic_memory(
    agent_id: str, 
    query: str = Query(..., description="Query string for semantic search"), 
    limit: int = 5, 
    db: Session = Depends(get_db)
):
    try:
        results = memory_engine.search_semantic_memory(db, agent_id, query, limit)
        return {"agent_id": agent_id, "query": query, "results": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
