import os
import sys

def compile():
    print("Compiling protobuf files...")
    try:
        from grpc_tools import protoc
    except ImportError:
        print("Error: grpcio-tools is not installed. Run 'pip install grpcio-tools' first.")
        sys.exit(1)
        
    os.makedirs("protos", exist_ok=True)
    
    # Run protoc
    # This generates protos/agentos_pb2.py and protos/agentos_pb2_grpc.py
    proto_path = os.path.join("protos", "agentos.proto")
    command = [
        "",
        "-I.",
        "--python_out=.",
        "--grpc_python_out=.",
        proto_path
    ]
    
    exit_code = protoc.main(command)
    if exit_code == 0:
        print("Protobuf compilation completed successfully. ✅")
        # Ensure __init__.py exists in protos folder to make it a package
        with open(os.path.join("protos", "__init__.py"), "a") as f:
            pass
    else:
        print(f"Protobuf compilation failed with exit code: {exit_code}")
        sys.exit(exit_code)

if __name__ == "__main__":
    compile()
