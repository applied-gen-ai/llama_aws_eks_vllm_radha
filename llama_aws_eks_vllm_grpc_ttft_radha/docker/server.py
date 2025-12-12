import os
import time
import asyncio
import uuid
from contextlib import asynccontextmanager

import grpc
from vllm.engine.arg_utils import AsyncEngineArgs as EngineArgs
from vllm.engine.async_llm_engine import AsyncLLMEngine
from vllm import SamplingParams
from grpc import aio, StatusCode
from grpc_reflection.v1alpha import reflection
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
from prometheus_client import start_http_server, Gauge, Counter, Histogram

import llm_grpc.llm_pb2 as pb
import llm_grpc.llm_pb2_grpc as pbg

# -------------------------
# Env / config
# -------------------------
MODEL_ID = os.getenv("MODEL_ID", "stabilityai/stablelm-3b-4e1t")
DTYPE = os.getenv("DTYPE", "float16")
TP = int(os.getenv("TENSOR_PARALLEL_SIZE", "1"))
PORT = int(os.getenv("GRPC_PORT", "50051"))
METRICS_PORT = int(os.getenv("METRICS_PORT", "8000"))
MAX_INFLIGHT = int(os.getenv("MAX_INFLIGHT", "512"))  # target concurrency limit

# Identify this pod (Kubernetes injects HOSTNAME)
POD_NAME = os.getenv("HOSTNAME", "unknown-pod")
NAMESPACE = os.getenv("NAMESPACE", "default")

# -------------------------
# Prometheus metrics
# -------------------------
QUEUE_LENGTH = Gauge(
    "llm_request_queue_length",
    "Number of requests waiting for admission to vLLM (per pod).",
    ["namespace", "pod"],
)
INFLIGHT = Gauge(
    "llm_requests_in_flight",
    "Number of requests currently being processed by this pod.",
    ["namespace", "pod"],
)
REQ_TOTAL = Counter("llm_requests_total", "Total LLM requests received.", ["namespace", "pod"])
REQ_FAILED = Counter("llm_requests_failed_total", "Total LLM requests failed.", ["namespace", "pod"])
TTFT_HIST = Histogram(
    "llm_ttft_ms",
    "Time to first token in milliseconds.",
    buckets=[10, 25, 50, 100, 200, 400, 800, 1600, 3200, 6400, 12800],
    labelnames=["namespace", "pod"],
)
VLLM_INTERNAL_WAITING = Gauge(
    "vllm_internal_waiting_requests",
    "Requests waiting inside vLLM scheduler (debug/visibility).",
    ["namespace", "pod"],
)
MAX_INFLIGHT_GAUGE = Gauge(
    "vllm_config_max_inflight",
    "Configured vLLM scheduler max_num_requests (for debug).",
    ["namespace", "pod"],
)

# -------------------------
# Admission control
# -------------------------
admission_sem = asyncio.Semaphore(MAX_INFLIGHT)
admission_queue = asyncio.Queue()


@asynccontextmanager
async def admission_guard():
    """Enforce bounded concurrency and expose queue length as metric."""
    await admission_queue.put(1)
    QUEUE_LENGTH.labels(namespace=NAMESPACE, pod=POD_NAME).set(admission_queue.qsize())

    await admission_sem.acquire()
    try:
        try:
            admission_queue.get_nowait()
            admission_queue.task_done()
        except asyncio.QueueEmpty:
            pass
        QUEUE_LENGTH.labels(namespace=NAMESPACE, pod=POD_NAME).set(admission_queue.qsize())

        INFLIGHT.labels(namespace=NAMESPACE, pod=POD_NAME).inc()
        try:
            yield
        finally:
            INFLIGHT.labels(namespace=NAMESPACE, pod=POD_NAME).dec()
    finally:
        admission_sem.release()


# -------------------------
# LLM Service
# -------------------------
class LLMService(pbg.LLMServicer):
    def __init__(self):
        # Base engine args
        engine_args = EngineArgs(
            model=MODEL_ID,
            dtype=DTYPE,
            tensor_parallel_size=TP,
            trust_remote_code=True,
            max_num_seqs=512,
            max_num_batched_tokens=8192,
            gpu_memory_utilization=0.95,
        )

        # Initialize engine first
        self.engine = AsyncLLMEngine.from_engine_args(engine_args)

        # Now modify scheduler config safely
        try:
            self.engine.engine_config.scheduler_config.max_num_requests = MAX_INFLIGHT
            self.engine.engine_config.scheduler_config.max_num_batched_tokens = 8192
            print(f"[Init] Updated scheduler max_num_requests = {MAX_INFLIGHT}")
        except Exception as e:
            print(f"[Warning] Could not update scheduler config dynamically: {e}")

        MAX_INFLIGHT_GAUGE.labels(namespace=NAMESPACE, pod=POD_NAME).set(MAX_INFLIGHT)
        print(f"[Confirm] Engine initialized for model={MODEL_ID}, dtype={DTYPE}, TP={TP}")

    # -------------------------
    # Generate RPC
    # -------------------------
    async def Generate(self, request: pb.GenerateRequest, context: aio.ServicerContext):
        REQ_TOTAL.labels(namespace=NAMESPACE, pod=POD_NAME).inc()
        try:
            params = SamplingParams(
                max_tokens=request.max_new_tokens or 50,
                temperature=request.temperature if request.temperature > 0 else 0.8,
            )

            req_id = f"req-{uuid.uuid4().hex}"
            t0 = time.time()
            first_token = False
            full_text = ""

            async with admission_guard():
                async for out in self.engine.generate(request.prompt, params, request_id=req_id):
                    if not out.outputs:
                        continue
                    full_text = out.outputs[0].text or ""

                    if not first_token and full_text:
                        TTFT_HIST.labels(namespace=NAMESPACE, pod=POD_NAME).observe(
                            (time.time() - t0) * 1000.0
                        )
                        first_token = True

            return pb.GenerateReply(text=full_text)

        except asyncio.CancelledError:
            return
        except Exception as e:
            REQ_FAILED.labels(namespace=NAMESPACE, pod=POD_NAME).inc()
            await context.abort(StatusCode.INTERNAL, f"vLLM error: {type(e).__name__}: {e}")

    # -------------------------
    # StreamGenerate RPC
    # -------------------------
    async def StreamGenerate(self, request: pb.GenerateRequest, context: aio.ServicerContext):
        REQ_TOTAL.labels(namespace=NAMESPACE, pod=POD_NAME).inc()
        try:
            params = SamplingParams(
                max_tokens=request.max_new_tokens or 50,
                temperature=request.temperature if request.temperature > 0 else 0.8,
            )

            req_id = f"req-{uuid.uuid4().hex}"
            last_len = 0
            t0 = time.time()
            first_token_sent = False

            async with admission_guard():
                async for out in self.engine.generate(request.prompt, params, request_id=req_id):
                    if not out.outputs:
                        continue
                    full_text = out.outputs[0].text or ""
                    if len(full_text) > last_len:
                        if not first_token_sent:
                            TTFT_HIST.labels(namespace=NAMESPACE, pod=POD_NAME).observe(
                                (time.time() - t0) * 1000.0
                            )
                            first_token_sent = True
                        chunk = full_text[last_len:]
                        last_len = len(full_text)
                        yield pb.Token(text=chunk, is_last=False)

            yield pb.Token(text="", is_last=True)

        except asyncio.CancelledError:
            return
        except Exception as e:
            REQ_FAILED.labels(namespace=NAMESPACE, pod=POD_NAME).inc()
            await context.abort(StatusCode.INTERNAL, f"vLLM error: {type(e).__name__}: {e}")


# -------------------------
# Monitor internal vLLM scheduler
# -------------------------
async def monitor_vllm_internal_queue(engine: AsyncLLMEngine):
    while True:
        try:
            stats = await engine.get_model_executor_status()
            waiting = getattr(stats, "num_waiting_requests", None)
            if isinstance(waiting, (int, float)):
                VLLM_INTERNAL_WAITING.labels(namespace=NAMESPACE, pod=POD_NAME).set(waiting)
        except Exception:
            pass
        await asyncio.sleep(5)


# -------------------------
# gRPC server entrypoint
# -------------------------
async def serve():
    start_http_server(METRICS_PORT)

    server = aio.server(
        options=[
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ]
    )

    svc = LLMService()
    pbg.add_LLMServicer_to_server(svc, server)

    health_svc = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_svc, server)
    SERVICE_NAMES = (
        pb.DESCRIPTOR.services_by_name["LLM"].full_name,
        health.SERVICE_NAME,
        reflection.SERVICE_NAME,
    )
    reflection.enable_server_reflection(SERVICE_NAMES, server)

    listen_addr = f"[::]:{PORT}"
    server.add_insecure_port(listen_addr)
    print(f"[gRPC] Listening on {listen_addr} (model={MODEL_ID})")

    health_svc.set("", health_pb2.HealthCheckResponse.SERVING)

    asyncio.create_task(monitor_vllm_internal_queue(svc.engine))
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    asyncio.run(serve())
