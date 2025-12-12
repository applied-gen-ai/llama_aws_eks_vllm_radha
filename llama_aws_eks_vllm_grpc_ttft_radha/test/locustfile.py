import os
import sys
import time
import grpc
import random
from dotenv import load_dotenv
from locust import User, task, between, events

# --------------------------------------------------------------------
# gRPC stubs (generated from llm.proto)
# --------------------------------------------------------------------
sys.path.insert(0, r"E:\llama_aws_eks_vllm_gRPC_radha\docker")
from llm_grpc import llm_pb2 as pb
from llm_grpc import llm_pb2_grpc as pbg

# --------------------------------------------------------------------
# Environment setup
# --------------------------------------------------------------------
load_dotenv()
GRPC_TARGET = os.getenv("LLM_TARGET")

# --------------------------------------------------------------------
# gRPC client wrapper
# --------------------------------------------------------------------
class GrpcLLMClient:
    """
    Thin wrapper around the gRPC stub:
      • connects to LLM server
      • exposes .generate()
      • reports metrics to Locust
    """

    def __init__(self, host: str):
        self.channel = grpc.insecure_channel(
            host,
            options=[
                ("grpc.keepalive_time_ms", 30000),
                ("grpc.keepalive_timeout_ms", 10000),
                ("grpc.http2.max_pings_without_data", 0),
                ("grpc.max_send_message_length", 50 * 1024 * 1024),
                ("grpc.max_receive_message_length", 50 * 1024 * 1024),
            ],
        )
        self.stub = pbg.LLMStub(self.channel)

    def generate(self, prompt: str, max_new_tokens: int = 10, temperature: float = 0.8):
        """Unary Generate RPC — returns final text only."""
        request = pb.GenerateRequest(
            prompt=prompt,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
        )

        start_time = time.time()
        try:
            response = self.stub.Generate(request, timeout=240)
            total_time = (time.time() - start_time) * 1000

            # Fire success event for Locust stats
            events.request.fire(
                request_type="gRPC",
                name="LLM.Generate",
                response_time=total_time,
                response_length=len(response.text),
                exception=None,
            )
            return response

        except Exception as e:
            total_time = (time.time() - start_time) * 1000
            events.request.fire(
                request_type="gRPC",
                name="LLM.Generate",
                response_time=total_time,
                response_length=0,
                exception=e,
            )
            raise

# --------------------------------------------------------------------
# Locust User class
# --------------------------------------------------------------------
class LLMUser(User):
    """
    Locust 'User' that:
      • waits 0.01-0.09 s between requests
      • connects to the gRPC client on start
      • sends Generate RPCs repeatedly
    """
    wait_time = between(0.01, 0.09)

    def on_start(self):
        self.client = GrpcLLMClient(GRPC_TARGET)

    @task(1)
    def generate_text(self):
        prompts = [
            "What is the capital city of Japan?",
            "Tell me a Kubernetes joke.",
            "How does a transformer model work?",
            "What is the future of AI?",
            "Explain quantum computing in 1 sentence."
        ]
        prompt = random.choice(prompts)
        self.client.generate(prompt, max_new_tokens=10)

# --------------------------------------------------------------------
# Global event listeners (Locust 2.30+ compatible)
# --------------------------------------------------------------------
LOCUST_ENV = None  # store global environment reference

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    global LOCUST_ENV
    LOCUST_ENV = environment
    print("Test started!")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    print("Test finished!")

@events.request.add_listener
def on_request(
    request_type,
    name,
    response_time,
    response_length,
    exception,
    context=None,
    **kwargs
):
    """Periodic request-level logging."""
    try:
        global LOCUST_ENV
        runner = LOCUST_ENV.runner if LOCUST_ENV else None
        user_count = runner.user_count if runner else 0

        if exception is None and random.random() < 0.01:
            print(f"Active users: {user_count}, Avg response: {response_time:.2f} ms")

    except Exception as e:
        print(f"[on_request listener error] {e}")
