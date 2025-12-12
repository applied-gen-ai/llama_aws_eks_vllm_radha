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

# ---- Default target (replace with your NLB DNS if needed) ----
DEFAULT_TARGET = "a2a7e71d2d85d4f1f95b2ecaef7457e7-1929238506.us-east-1.elb.amazonaws.com:50051"
TARGET = os.environ.get("LLM_TARGET", DEFAULT_TARGET)

OPTS = [
    ("grpc.keepalive_time_ms", 30000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.max_send_message_length", 50 * 1024 * 1024),
    ("grpc.max_receive_message_length", 50 * 1024 * 1024),
]

# ---- Worker for single request ----
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


# ---- Single benchmark run ----
def benchmark_concurrent(prompts, concurrency=10):
    results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(run_request, prompts[i % len(prompts)], i)
            for i in range(concurrency)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    results.sort(key=lambda x: x["id"])

    valid_ttfts = [r["ttft_ms"] for r in results if r.get("ttft_ms")]
    valid_totals = [r["total_ms"] for r in results if r.get("total_ms")]

    avg_ttft = sum(valid_ttfts) / len(valid_ttfts) if valid_ttfts else 0
    avg_total = sum(valid_totals) / len(valid_totals) if valid_totals else 0

    print(f"Run completed: {len(valid_ttfts)} requests | "
          f"Avg TTFT={avg_ttft:.1f} ms | Avg Total={avg_total:.1f} ms")

    return avg_ttft, avg_total, valid_ttfts


# ---- Multi-run executor ----
def benchmark_multi_run(prompts, concurrency=10, runs=10):
    all_run_avg_ttfts = []
    all_run_avg_totals = []
    all_ttfts_across_runs = []

    print(f"\n=== Running {runs} Benchmark Iterations (Concurrency={concurrency}) ===\n")

    for i in range(1, runs + 1):
        print(f"\n--- Run {i}/{runs} ---")
        run_avg_ttft, run_avg_total, ttfts = benchmark_concurrent(prompts, concurrency)
        all_run_avg_ttfts.append(run_avg_ttft)
        all_run_avg_totals.append(run_avg_total)
        all_ttfts_across_runs.extend(ttfts)

    # Compute averages across all runs
    overall_avg_ttft = sum(all_run_avg_ttfts) / len(all_run_avg_ttfts)
    overall_avg_total = sum(all_run_avg_totals) / len(all_run_avg_totals)
    overall_avg_of_all_ttfts = sum(all_ttfts_across_runs) / len(all_ttfts_across_runs)

    print("\n=== Final Summary Across All Runs ===")
    print(f"Average TTFT per Run:        {overall_avg_ttft:.2f} ms")
    print(f"Average Total Time per Run:  {overall_avg_total:.2f} ms")
    print(f"Average of All TTFTs:        {overall_avg_of_all_ttfts:.2f} ms")


if __name__ == "__main__":
    prompts = [
        "What is the capital city of Japan?",
        "Explain reinforcement learning briefly.",
        "What is Kubernetes?",
        "Tell me a joke about AI.",
        "Summarize the movie Inception."
    ]

    benchmark_multi_run(prompts, concurrency=5000, runs=10)
