import os
import sys
import yaml
import logging
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()
import grpc

from storage.database import init_db, get_db, AgentManifestTable, AgentVersionTable, AgentInstanceTable, TaskTable, CheckpointTable, ToolCallTable
from core.event_bus import EventBus
from core.workflow.engine import WorkflowEngine

# Initialize database on startup
init_db()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentos.api.server")

app = FastAPI(
    title="AgentOS API Gateway", 
    description="The Operating System for Autonomous AI Agents - Milestone 2 (Distributed)",
    version="2.0"
)

# Configuration for gRPC targets
REGISTRY_TARGET = "localhost:50053"
MEMORY_TARGET = "localhost:50052"

# Event Bus and Workflow Engine setup
event_bus = EventBus()
workflow_engine = WorkflowEngine(event_bus)

@app.on_event("startup")
async def startup_event():
    await event_bus.connect()

@app.on_event("shutdown")
async def shutdown_event():
    await event_bus.close()

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

class WorkflowRunRequest(BaseModel):
    workflow_yaml: str
    context: Dict[str, Any]


@app.get("/")
def read_root():
    return {
        "status": "online",
        "system": "AgentOS",
        "version": "2.0-milestone2",
        "architecture": "Distributed gRPC & NATS",
        "subsystems": {
            "api_gateway": "ready",
            "event_bus": "connected" if event_bus.connected else "in-memory-fallback"
        }
    }


# --- Agent Registration (gRPC Proxy) ---
@app.post("/v1/agents")
def register_agent(req: RegisterAgentRequest):
    try:
        with grpc.insecure_channel(REGISTRY_TARGET) as channel:
            stub = pb2_grpc.AgentRegistryServiceStub(channel)
            grpc_req = pb2.RegisterAgentRequest(manifest_yaml=req.manifest_yaml)
            response = stub.RegisterAgent(grpc_req, timeout=10.0)
            
            if response.status == "failed":
                raise HTTPException(status_code=400, detail="Manifest registration failed on Registry Server.")
                
            return {
                "id": response.id,
                "name": response.name,
                "registered_version": response.version,
                "status": "success"
            }
    except grpc.RpcError as e:
        logger.error(f"Registry gRPC error: {e}")
        raise HTTPException(status_code=502, detail=f"Registry Plane unavailable: {e.details()}")


@app.get("/v1/agents/{id}")
def get_agent_manifest(id: str):
    try:
        with grpc.insecure_channel(REGISTRY_TARGET) as channel:
            stub = pb2_grpc.AgentRegistryServiceStub(channel)
            grpc_req = pb2.GetAgentRequest(id=id)
            response = stub.GetAgent(grpc_req, timeout=5.0)
            
            return {
                "id": response.id,
                "name": response.name,
                "description": response.description,
                "latest_version": response.latest_version,
                "manifest_yaml": response.manifest_yaml
            }
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail=e.details())
        logger.error(f"Registry gRPC error: {e}")
        raise HTTPException(status_code=502, detail=f"Registry Plane unavailable: {e.details()}")


# --- Task Submission (NATS Event-Driven) ---
@app.post("/v1/agents/{id}/tasks")
async def submit_task(id: str, req: SubmitTaskRequest, db: Session = Depends(get_db)):
    # Retrieve manifest from Registry Server to verify existence
    try:
        with grpc.insecure_channel(REGISTRY_TARGET) as channel:
            stub = pb2_grpc.AgentRegistryServiceStub(channel)
            grpc_req = pb2.GetAgentRequest(id=id)
            agent_manifest = stub.GetAgent(grpc_req, timeout=5.0)
    except grpc.RpcError as e:
        if e.code() == grpc.StatusCode.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Agent manifest not found")
        raise HTTPException(status_code=502, detail="Registry Plane unavailable")

    # Get default instance
    instance = db.query(AgentInstanceTable).filter(
        AgentInstanceTable.manifest_id == id,
        AgentInstanceTable.version == agent_manifest.latest_version
    ).first()
    
    if not instance:
        instance = AgentInstanceTable(
            manifest_id=id,
            version=agent_manifest.latest_version,
            status="REGISTERED"
        )
        db.add(instance)
        db.commit()

    # Create task in database
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

    # Publish tasks.queued event to NATS EventBus
    await event_bus.publish("tasks.queued", {
        "task_id": task.id,
        "agent_id": id,
        "input": req.input,
        "priority": req.priority
    })

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

    checkpoints_count = db.query(CheckpointTable).filter(CheckpointTable.task_id == id).count()
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


# --- Semantic Memory (gRPC Proxy) ---
@app.post("/v1/memory/{agent_id}/semantic")
def add_semantic_memory(agent_id: str, req: SemanticMemoryAddRequest):
    try:
        with grpc.insecure_channel(MEMORY_TARGET) as channel:
            stub = pb2_grpc.MemoryEngineServiceStub(channel)
            grpc_req = pb2.SaveMemoryRequest(agent_id=agent_id, text=req.text)
            response = stub.SaveMemory(grpc_req, timeout=10.0)
            return {"status": response.status}
    except grpc.RpcError as e:
        logger.error(f"Memory gRPC error: {e}")
        raise HTTPException(status_code=502, detail=f"Memory Plane unavailable: {e.details()}")


@app.get("/v1/memory/{agent_id}/semantic")
def search_semantic_memory(
    agent_id: str, 
    query: str = Query(..., description="Query string"), 
    limit: int = 5
):
    try:
        with grpc.insecure_channel(MEMORY_TARGET) as channel:
            stub = pb2_grpc.MemoryEngineServiceStub(channel)
            grpc_req = pb2.SearchMemoryRequest(agent_id=agent_id, query=query, limit=limit)
            response = stub.SearchMemory(grpc_req, timeout=10.0)
            
            matches = [{
                "text": r.text,
                "similarity": r.similarity,
                "created_at": r.created_at
            } for r in response.results]
            return {"agent_id": agent_id, "query": query, "results": matches}
    except grpc.RpcError as e:
        logger.error(f"Memory gRPC error: {e}")
        raise HTTPException(status_code=502, detail=f"Memory Plane unavailable: {e.details()}")


# --- Distributed Workflows (Coordination Plane) ---
@app.post("/v1/workflows/run")
async def run_workflow(req: WorkflowRunRequest, background_tasks: BackgroundTasks):
    # Runs the workflow asynchronously in the background so HTTP connection isn't blocked
    async def run_workflow_task():
        # Create a clean loop-isolated EventBus and run it
        w_bus = EventBus()
        await w_bus.connect()
        w_engine = WorkflowEngine(w_bus)
        try:
            await w_engine.execute_workflow(req.workflow_yaml, req.context)
        finally:
            await w_bus.close()

    background_tasks.add_task(run_workflow_task)
    return {"status": "triggered", "message": "Workflow started in background."}
