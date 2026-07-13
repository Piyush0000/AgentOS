import os
import sys
import logging
from concurrent import futures
import grpc
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()
from memory.engine import MemoryEngine
from storage.database import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentos.memory.server")

class CognitionGatewayClientProxy:
    """Proxy object implementing get_embedding by calling the Cognition Plane gRPC Server."""
    def __init__(self, channel_target="localhost:50051"):
        self.target = channel_target

    def get_embedding(self, text: str):
        try:
            with grpc.insecure_channel(self.target) as channel:
                stub = pb2_grpc.LLMGatewayServiceStub(channel)
                response = stub.GetEmbedding(pb2.GetEmbeddingRequest(text=text), timeout=5.0)
                return list(response.embedding)
        except Exception as e:
            logger.error(f"Failed to fetch embedding from Cognition gRPC Server: {e}")
            # Fallback to deterministic pseudo-random mock embedding
            import random
            h_text = 5381
            for char in text:
                h_text = ((h_text << 5) + h_text) + ord(char)
            random.seed(h_text)
            vector = [random.uniform(-1, 1) for _ in range(1536)]
            norm = sum(x*x for x in vector) ** 0.5
            return [x / norm for x in vector]

class MemoryEngineService(pb2_grpc.MemoryEngineServiceServicer):
    def __init__(self):
        # Initialize MemoryEngine using the Cognition client proxy
        proxy = CognitionGatewayClientProxy()
        self.engine = MemoryEngine(llm_gateway=proxy)

    def SaveMemory(self, request, context):
        logger.info(f"Received SaveMemory request for agent={request.agent_id}")
        db: Session = SessionLocal()
        try:
            self.engine.save_semantic_memory(db, request.agent_id, request.text)
            return pb2.SaveMemoryResponse(status="success")
        except Exception as e:
            logger.error(f"Error in SaveMemory: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.SaveMemoryResponse(status="failed")
        finally:
            db.close()

    def SearchMemory(self, request, context):
        logger.info(f"Received SearchMemory request for agent={request.agent_id}, query='{request.query}'")
        db: Session = SessionLocal()
        try:
            results = self.engine.search_semantic_memory(
                db, 
                request.agent_id, 
                request.query, 
                limit=request.limit
            )
            
            # Map memory search results to protobuf
            grpc_matches = []
            for r in results:
                grpc_matches.append(pb2.MemoryMatch(
                    text=r["text"],
                    similarity=r["similarity"],
                    created_at=r["created_at"].isoformat()
                ))
            return pb2.SearchMemoryResponse(results=grpc_matches)
        except Exception as e:
            logger.error(f"Error in SearchMemory: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.SearchMemoryResponse()
        finally:
            db.close()

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_MemoryEngineServiceServicer_to_server(MemoryEngineService(), server)
    port = "[::]:50052"
    server.add_insecure_port(port)
    logger.info("Memory Plane gRPC Server running on port 50052...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
