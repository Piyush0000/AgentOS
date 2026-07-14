import os
import sys
import json
import logging
from concurrent import futures
import grpc

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()
from cognition.gateway.llm import LLMGateway

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentos.cognition.server")

class LLMGatewayService(pb2_grpc.LLMGatewayServiceServicer):
    def __init__(self):
        self.gateway = LLMGateway()

    def GenerateCompletion(self, request, context):
        logger.info(f"Received GenerateCompletion request for model={request.model}")
        
        # Translate gRPC messages to list of dicts
        messages = []
        for msg in request.messages:
            msg_dict = {
                "role": msg.role,
                "content": msg.content
            }
            if msg.tool_call_id:
                msg_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                msg_dict["name"] = msg.name
            messages.append(msg_dict)
            
        # Translate gRPC tools schema to dicts
        tools = []
        for t in request.tools:
            tools.append({
                "name": t.name,
                "description": t.description,
                "parameters": json.loads(t.parameters_json) if t.parameters_json else {}
            })
            
        try:
            provider = getattr(request, "provider", "")
            api_key = getattr(request, "api_key", "")
            response = self.gateway.generate_chat_completion(
                model=request.model,
                messages=messages,
                tools=tools if tools else None,
                provider=provider if provider else None,
                api_key=api_key if api_key else None
            )
            
            # Map LLMResponse back to gRPC response message
            grpc_tool_calls = []
            for tc in response.tool_calls:
                grpc_tool_calls.append(pb2.ToolCall(
                    id=tc["id"],
                    name=tc["name"],
                    arguments_json=json.dumps(tc["arguments"])
                ))
                
            return pb2.GenerateCompletionResponse(
                content=response.content or "",
                tool_calls=grpc_tool_calls
            )
        except Exception as e:
            logger.error(f"Error in GenerateCompletion: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GenerateCompletionResponse()

    def GetEmbedding(self, request, context):
        logger.info("Received GetEmbedding request")
        try:
            embedding = self.gateway.get_embedding(request.text)
            return pb2.GetEmbeddingResponse(embedding=embedding)
        except Exception as e:
            logger.error(f"Error in GetEmbedding: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GetEmbeddingResponse()

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_LLMGatewayServiceServicer_to_server(LLMGatewayService(), server)
    port = "[::]:50051"
    server.add_insecure_port(port)
    logger.info(f"Cognition Plane gRPC Server running on port 50051...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
