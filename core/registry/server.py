import os
import sys
import yaml
import logging
from concurrent import futures
import grpc
from sqlalchemy.orm import Session

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from protos.loader import load_grpc_protos
pb2, pb2_grpc = load_grpc_protos()
from storage.database import SessionLocal, AgentManifestTable, AgentVersionTable
from core.manifest.models import AgentManifest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agentos.core.registry.server")

class AgentRegistryService(pb2_grpc.AgentRegistryServiceServicer):
    def RegisterAgent(self, request, context):
        logger.info("Received RegisterAgent gRPC request")
        db: Session = SessionLocal()
        try:
            # Parse & validate manifest YAML
            manifest_data = yaml.safe_load(request.manifest_yaml)
            manifest = AgentManifest(**manifest_data)
            
            # Check if manifest already exists in manifest table
            manifest_record = db.query(AgentManifestTable).filter(AgentManifestTable.id == manifest.id).first()
            if not manifest_record:
                manifest_record = AgentManifestTable(
                    id=manifest.id,
                    name=manifest.name,
                    description=manifest.description
                )
                db.add(manifest_record)
                db.commit()

            # Add version record
            latest_version = db.query(AgentVersionTable).filter(
                AgentVersionTable.manifest_id == manifest.id
            ).order_by(AgentVersionTable.version.desc()).first()
            
            next_ver = (latest_version.version + 1) if latest_version else 1
            
            version_record = AgentVersionTable(
                manifest_id=manifest.id,
                version=next_ver,
                manifest_yaml=request.manifest_yaml
            )
            db.add(version_record)
            db.commit()
            
            logger.info(f"Successfully registered agent manifest {manifest.id} version {next_ver}")
            return pb2.RegisterAgentResponse(
                id=manifest.id,
                name=manifest.name,
                version=next_ver,
                status="success"
            )
        except Exception as e:
            logger.error(f"Error registering manifest: {e}")
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(str(e))
            return pb2.RegisterAgentResponse(status="failed")
        finally:
            db.close()

    def GetAgent(self, request, context):
        logger.info(f"Received GetAgent request for id={request.id}")
        db: Session = SessionLocal()
        try:
            manifest_record = db.query(AgentManifestTable).filter(AgentManifestTable.id == request.id).first()
            if not manifest_record:
                context.set_code(grpc.StatusCode.NOT_FOUND)
                context.set_details(f"Agent manifest '{request.id}' not found.")
                return pb2.GetAgentResponse()

            latest_version = db.query(AgentVersionTable).filter(
                AgentVersionTable.manifest_id == request.id
            ).order_by(AgentVersionTable.version.desc()).first()

            return pb2.GetAgentResponse(
                id=manifest_record.id,
                name=manifest_record.name,
                description=manifest_record.description or "",
                latest_version=latest_version.version if latest_version else 0,
                manifest_yaml=latest_version.manifest_yaml if latest_version else ""
            )
        except Exception as e:
            logger.error(f"Error fetching manifest: {e}")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(str(e))
            return pb2.GetAgentResponse()
        finally:
            db.close()

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    pb2_grpc.add_AgentRegistryServiceServicer_to_server(AgentRegistryService(), server)
    port = "[::]:50053"
    server.add_insecure_port(port)
    logger.info("Agent Registry gRPC Server running on port 50053...")
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
