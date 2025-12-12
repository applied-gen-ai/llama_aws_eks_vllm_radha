# Use NVIDIA base image with CUDA for GPU inference
FROM nvidia/cuda:12.1.1-runtime-ubuntu22.04

WORKDIR /app

# --- System deps ---
RUN apt-get update && apt-get install -y \
    python3 python3-pip git \
 && ln -s /usr/bin/python3 /usr/bin/python \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# --- Python deps (your project requirements first) ---
COPY requirements.txt .
RUN pip install --default-timeout=1000 -r requirements.txt

# --- gRPC explicit pins (stability) ---
RUN pip install \
    grpcio==1.65.5 \
    grpcio-tools==1.65.5 \
    grpcio-reflection==1.65.5 \
    grpcio-health-checking==1.65.5

# --- Prometheus client for /metrics (new) ---
RUN pip install prometheus_client

# --- App code ---
# Proto stubs should already be generated into llm_grpc/ before build
COPY llm_grpc/ ./llm_grpc/
COPY server.py .

# --- Ports ---
# gRPC
EXPOSE 50051
# Prometheus metrics (new)
EXPOSE 8000

# --- Runtime env (can be overridden via Deployment) ---
ENV GRPC_PORT=50051 \
    METRICS_PORT=8000 \
    MAX_INFLIGHT=16

# Entrypoint: run gRPC server
CMD ["python", "server.py"]
