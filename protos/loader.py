import os
import sys
import importlib

def load_grpc_protos():
    """
    Programmatically compiles protos if they are missing, 
    and returns (agentos_pb2, agentos_pb2_grpc) modules.
    """
    pb2_path = os.path.join("protos", "agentos_pb2.py")
    pb2_grpc_path = os.path.join("protos", "agentos_pb2_grpc.py")
    
    if not os.path.exists(pb2_path) or not os.path.exists(pb2_grpc_path):
        print("Generated proto bindings not found. Compiling now...")
        import compile_protos
        compile_protos.compile()
        
    # Add root folder to path to resolve imports inside generated files
    root_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    if root_dir not in sys.path:
        sys.path.insert(0, root_dir)
        
    # Import the modules
    agentos_pb2 = importlib.import_module("protos.agentos_pb2")
    agentos_pb2_grpc = importlib.import_module("protos.agentos_pb2_grpc")
    
    return agentos_pb2, agentos_pb2_grpc
