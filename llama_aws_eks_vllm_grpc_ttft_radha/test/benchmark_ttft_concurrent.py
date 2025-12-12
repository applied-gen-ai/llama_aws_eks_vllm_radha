import os
import sys
import time
import grpc
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---- Import gRPC stubs ----
sys.path.insert(0, r"E:\llama_aws_eks_vllm_gRPC_radha\docker")
from llm_grpc import llm_pb2 as pb
from llm_grpc import llm_pb2_grpc as pbg

load_dotenv()
TARGET = os.getenv("LLM_TARGET")

DEFAULT_TARGET = TARGET

# ---- Target (replace with your working NLB DNS if needed) ----
DEFAULT_TARGET = "a2a7e71d2d85d4f1f95b2ecaef7457e7-1929238506.us-east-1.elb.amazonaws.com:50051"
TARGET = os.environ.get("LLM_TARGET", DEFAULT_TARGET)

OPTS = [
    ("grpc.keepalive_time_ms", 30000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.max_send_message_length", 50 * 1024 * 1024),
    ("grpc.max_receive_message_length", 50 * 1024 * 1024),
]

# ---- Worker function for a single request ----
def run_request(prompt: str, idx: int, max_new_tokens: int = 10, temperature: float = 0.7):
    channel = grpc.insecure_channel(TARGET, options=OPTS)
    grpc.channel_ready_future(channel).result(timeout=30)
    stub = pbg.LLMStub(channel)

    request = pb.GenerateRequest(
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
    )

    start_time = time.time()
    ttft = None
    reply_text = ""

    try:
        responses = stub.StreamGenerate(request, timeout=300)
        for token in responses:
            if ttft is None:
                ttft = (time.time() - start_time) * 1000
            if token.is_last:
                break
            reply_text += token.text
        total_time = (time.time() - start_time) * 1000
        return {
            "id": idx,
            "ttft_ms": ttft,
            "total_ms": total_time,
            "reply": reply_text[:60] + ("..." if len(reply_text) > 60 else ""),
        }
    except grpc.RpcError as e:
        return {
            "id": idx,
            "ttft_ms": None,
            "total_ms": None,
            "error": f"{e.code()} {e.details()}",
        }
    finally:
        channel.close()

# ---- Benchmark runner ----
def benchmark_concurrent(prompts, concurrency=10):
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(run_request, prompts[i % len(prompts)], i)
            for i in range(concurrency)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    # Sort by request id
    results.sort(key=lambda x: x["id"])

    print("\n=== TTFT Benchmark Results ===")
    for r in results:
        if "error" in r:
            print(f"Req {r['id']}: ERROR {r['error']}")
        else:
            print(f"Req {r['id']}: TTFT={r['ttft_ms']:.1f} ms, "
                  f"Total={r['total_ms']:.1f} ms, "
                  f"Reply={r['reply']}")

    valid_ttfts = [r["ttft_ms"] for r in results if r.get("ttft_ms")]
    if valid_ttfts:
        avg_ttft = sum(valid_ttfts) / len(valid_ttfts)
        print(f"\nAverage TTFT across {len(valid_ttfts)} reqs: {avg_ttft:.1f} ms")


if __name__ == "__main__":
    prompts = [
        "What is the capital city of Japan?",
        "Explain reinforcement learning briefly.",
        "What is Kubernetes?",
        "Tell me a joke about AI.",
        "Summarize the movie Inception."
    ]

    benchmark_concurrent(prompts, concurrency=10000)
