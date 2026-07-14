FROM python:3.10-slim

WORKDIR /app

# Install standard system utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source tree
COPY . .

# Compile gRPC protobuf bindings
RUN python compile_protos.py

# Expose ports for all decoupled planes & gateway:
# 8000 (API Gateway / Dashboard)
# 50051 (Cognition Plane)
# 50052 (Memory Plane)
# 50053 (Registry Plane)
# 50054 (Runtime Plane)
EXPOSE 8000 50051 50052 50053 50054

# Default command can be overridden per container service definition
CMD ["python"]
