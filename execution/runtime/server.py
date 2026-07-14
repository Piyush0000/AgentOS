import os
import sys
import json
import logging
from concurrent import futures
import grpc
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()
from execution.runtime.engine import AgentRuntime
from memory.engine import MemoryEngine
from execution.sandbox.runner import ToolRunner
from storage.database import SessionLocal
from cognition.gateway.llm import LLMResponse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentos.execution.runtime.server")

class gRPCLLMGatewayProxy:
    """Proxy that forwards LLM completions to the Cognition Plane gRPC Server."""
    def __init__(self, target="localhost:50051"):
        self.target = target

    def generate_chat_completion(self, model: str, messages: list, tools: list = None, provider: str = None, api_key: str = None):
        logger.info(f"Forwarding generate_chat_completion to Cognition Server at {self.target} (provider: {provider})")
        
        # Build gRPC messages
        grpc_msgs = []
        for m in messages:
            grpc_msgs.append(pb2.Message(
                role=m["role"],
                content=m["content"],
                tool_call_id=m.get("tool_call_id", ""),
                name=m.get("name", "")
            ))
            
        # Build gRPC tools
        grpc_tools = []
        if tools:
            for t in tools:
                grpc_tools.append(pb2.Tool(
                    name=t["name"],
                    description=t.get("description", ""),
                    parameters_json=json.dumps(t.get("parameters", {}))
                ))
                
        try:
            with grpc.insecure_channel(self.target) as channel:
                stub = pb2_grpc.LLMGatewayServiceStub(channel)
                req = pb2.GenerateCompletionRequest(
                    model=model,
                    messages=grpc_msgs,
                    tools=grpc_tools,
                    provider=provider or "",
                    api_key=api_key or ""
                )
                response = stub.GenerateCompletion(req, timeout=60.0)
                
                # Convert back to LLMResponse
                tool_calls = []
                for tc in response.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "name": tc.name,
                        "arguments": json.loads(tc.arguments_json)
                    })
                return LLMResponse(content=response.content, tool_calls=tool_calls)
        except Exception as e:
            logger.error(f"Error calling Cognition gRPC Server: {e}")
            raise e

    def get_embedding(self, text: str):
        try:
            with grpc.insecure_channel(self.target) as channel:
                stub = pb2_grpc.LLMGatewayServiceStub(channel)
                response = stub.GetEmbedding(pb2.GetEmbeddingRequest(text=text), timeout=5.0)
                return list(response.embedding)
        except Exception as e:
            logger.error(f"Error calling GetEmbedding on Cognition Server: {e}")
            raise e

class AgentRuntimeService(pb2_grpc.AgentRuntimeServiceServicer):
    def __init__(self):
        cognition_target = os.getenv("COGNITION_TARGET", "localhost:50051")
        llm_proxy = gRPCLLMGatewayProxy(target=cognition_target)
        # Initialize the local memory engine, but pass the llm_proxy so it calls Cognition Plane for summarization
        memory_engine = MemoryEngine(llm_gateway=llm_proxy)
        tool_runner = ToolRunner()
        self.runtime = AgentRuntime(llm_proxy, memory_engine, tool_runner)

    def ExecuteTask(self, request, context):
        logger.info(f"Received ExecuteTask gRPC request for task_id={request.task_id}")
        db: Session = SessionLocal()
        try:
            result = self.runtime.execute_task(db, request.task_id)
            return pb2.ExecuteTaskResponse(
                task_id=result.get("task_id", ""),
                status=result.get("status", ""),
                output=result.get("output", ""),
                error=result.get("error", "")
            )
        except Exception as e:
            logger.error(f"Error executing task: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.ExecuteTaskResponse(
                task_id=request.task_id,
                status="FAILED",
                error=str(e)
            )
        finally:
            db.close()

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_AgentRuntimeServiceServicer_to_server(AgentRuntimeService(), server)
    port = "[::]:50054"
    server.add_insecure_port(port)
    logger.info("Agent Runtime gRPC Server running on port 50054...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
