#!/usr/bin/env python3
"""
client_measure_ttft_grpc.py
----------------------------------------
Purpose:
Concurrent client for measuring
 - TTFT (time-to-first-token)
 - Full latency
against a vLLM gRPC streaming endpoint.

Usage:
python client_measure_ttft_grpc.py <concurrency> <requests_per_client> <prompt> <max_tokens> <run_tag> [prometheus_url]

Example:
python client_measure_ttft_grpc.py 16 10 "Hello world" 64 mi350_c16 http://prometheus:9090
"""
import os
import sys
import time
import grpc
import csv
import uuid
import subprocess
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from statistics import mean, median
from dotenv import load_dotenv

# ---- Import gRPC stubs ----
sys.path.insert(0, r"E:\llama_aws_eks_vllm_gRPC_radha\docker")
from llm_grpc import llm_pb2 as pb
from llm_grpc import llm_pb2_grpc as pbg

load_dotenv()

# ---- Default target ----
DEFAULT_TARGET = "a2a7e71d2d85d4f1f95b2ecaef7457e7-1929238506.us-east-1.elb.amazonaws.com:50051"
TARGET = os.environ.get("LLM_TARGET", DEFAULT_TARGET)

OPTS = [
    ("grpc.keepalive_time_ms", 30000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.max_send_message_length", 50 * 1024 * 1024),
    ("grpc.max_receive_message_length", 50 * 1024 * 1024),
]

# Global for GPU monitoring process
gpu_monitor_proc = None


def start_gpu_monitoring(run_tag):
    """Start nvidia-smi dmon in background"""
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)
    log_file = os.path.join(results_dir, f"gpu_metrics_{run_tag}.log")
    
    try:
        proc = subprocess.Popen(
            ["nvidia-smi", "dmon", "-s", "pucm", "-d", "1", "-o", "T"],
            stdout=open(log_file, "w"),
            stderr=subprocess.PIPE
        )
        print(f"Started GPU monitoring → {log_file}")
        return proc
    except FileNotFoundError:
        print("[WARNING] nvidia-smi not found. Skipping GPU monitoring.")
        return None
    except Exception as e:
        print(f"[WARNING] Failed to start GPU monitoring: {e}")
        return None


def stop_gpu_monitoring(proc):
    """Stop GPU monitoring process"""
    if proc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
            print("Stopped GPU monitoring")
        except subprocess.TimeoutExpired:
            proc.kill()


def query_prometheus_queue_depth(prometheus_url, pod_pattern="llm-.*"):
    """Query average queue depth from Prometheus during test"""
    if not prometheus_url:
        return None
    
    try:
        query = f'avg(llm_request_queue_length{{pod=~"{pod_pattern}"}})'
        response = requests.get(
            f"{prometheus_url}/api/v1/query",
            params={"query": query},
            timeout=5
        )
        if response.status_code == 200:
            result = response.json()
            if result["data"]["result"]:
                return float(result["data"]["result"][0]["value"][1])
        return None
    except Exception as e:
        print(f"[WARNING] Failed to query Prometheus: {e}")
        return None


def single_request(prompt: str, max_new_tokens: int, temperature: float = 0.7):
    """
    Send a single streaming request and measure:
      - start time
      - time to first token
      - total time
    """
    req_id = str(uuid.uuid4())
    channel = grpc.insecure_channel(TARGET, options=OPTS)
    
    try:
        grpc.channel_ready_future(channel).result(timeout=30)
    except Exception as e:
        return {
            "id": req_id,
            "start": time.monotonic(),
            "first_token": None,
            "end": time.monotonic(),
            "status": -1,
            "error": f"Channel connection failed: {str(e)}"
        }
    
    stub = pbg.LLMStub(channel)
    request = pb.GenerateRequest(
        prompt=prompt,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
    )

    start = time.monotonic()
    first_token = None
    end = None
    status = 200

    try:
        responses = stub.StreamGenerate(request, timeout=300)
        for token in responses:
            now = time.monotonic()
            if first_token is None:
                first_token = now
            if token.is_last:
                break
        end = time.monotonic()
    except grpc.RpcError as e:
        status = -1
        end = time.monotonic()
        return {
            "id": req_id,
            "start": start,
            "first_token": first_token,
            "end": end,
            "status": status,
            "error": f"{e.code()} {e.details()}"
        }
    except Exception as e:
        status = -1
        end = time.monotonic()
        return {
            "id": req_id,
            "start": start,
            "first_token": first_token,
            "end": end,
            "status": status,
            "error": str(e)
        }
    finally:
        channel.close()

    return {
        "id": req_id,
        "start": start,
        "first_token": first_token,
        "end": end,
        "status": status
    }


def worker(client_id: int, num_requests: int, prompt: str, max_tokens: int):
    """
    One client performing sequential requests.
    """
    results = []
    for i in range(num_requests):
        res = single_request(prompt, max_tokens)
        results.append(res)
    return results


def run_all(concurrency: int, requests_per_client: int, prompt: str, max_tokens: int):
    """
    Launch all clients concurrently.
    """
    all_results = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [
            executor.submit(worker, i, requests_per_client, prompt, max_tokens)
            for i in range(concurrency)
        ]
        for f in as_completed(futures):
            all_results.extend(f.result())
    return all_results


def main():
    if len(sys.argv) < 6:
        print("Usage: python client_measure_ttft_grpc.py <concurrency> <requests_per_client> <prompt> <max_tokens> <run_tag> [prometheus_url]")
        print("Example: python client_measure_ttft_grpc.py 16 10 'Hello world' 64 mi350_c16")
        print("         python client_measure_ttft_grpc.py 16 10 'Hello world' 64 mi350_c16 http://prometheus:9090")
        sys.exit(1)

    concurrency = int(sys.argv[1])
    requests_per_client = int(sys.argv[2])
    prompt = sys.argv[3]
    max_tokens = int(sys.argv[4])
    run_tag = sys.argv[5]
    prometheus_url = sys.argv[6] if len(sys.argv) > 6 else None

    print(f"\n{'='*70}")
    print(f"{'gRPC TTFT Benchmark - Load Test':^70}")
    print(f"{'='*70}")
    print(f"Target:                  {TARGET}")
    print(f"Concurrency:             {concurrency}")
    print(f"Requests per client:     {requests_per_client}")
    print(f"Total requests:          {concurrency * requests_per_client}")
    print(f"Prompt:                  {prompt}")
    print(f"Max tokens:              {max_tokens}")
    print(f"Run tag:                 {run_tag}")
    if prometheus_url:
        print(f"Prometheus:              {prometheus_url}")
    print(f"{'='*70}\n")

    # Start GPU monitoring
    gpu_proc = start_gpu_monitoring(run_tag)
    
    # Query initial queue depth
    if prometheus_url:
        initial_queue = query_prometheus_queue_depth(prometheus_url)
        print(f"Initial queue depth: {initial_queue if initial_queue else 'N/A'}\n")
    
    # Run load test
    test_start = time.time()
    results = run_all(concurrency, requests_per_client, prompt, max_tokens)
    test_end = time.time()
    
    # Query final queue depth
    if prometheus_url:
        final_queue = query_prometheus_queue_depth(prometheus_url)
        print(f"\nFinal queue depth: {final_queue if final_queue else 'N/A'}")
    
    # Stop GPU monitoring
    stop_gpu_monitoring(gpu_proc)

    # Filter successful requests
    successful = [r for r in results if r["first_token"] is not None]
    failed = [r for r in results if r["first_token"] is None]

    if failed:
        print(f"\n[WARNING] {len(failed)} requests failed")
        for r in failed[:5]:  # Show first 5 errors
            if "error" in r:
                print(f"  - {r['error']}")

    if not successful:
        print("\n[ERROR] All requests failed. Cannot compute statistics.")
        sys.exit(1)

    # Compute TTFTs and latencies
    ttfts = [(r["first_token"] - r["start"]) for r in successful]
    full_lat = [(r["end"] - r["start"]) for r in successful]

    print(f"\n{'='*70}")
    print(f"{'Results Summary':^70}")
    print(f"{'='*70}")
    print(f"Run tag:                 {run_tag}")
    print(f"Total requests:          {len(results)}")
    print(f"Successful requests:     {len(successful)}")
    print(f"Failed requests:         {len(failed)}")
    print(f"Success rate:            {len(successful)/len(results)*100:.1f}%")
    
    print(f"\n{'TTFT Statistics':^70}")
    print(f"{'-'*70}")
    print(f"  p50:  {median(ttfts):.3f}s")
    print(f"  p95:  {sorted(ttfts)[int(len(ttfts)*0.95)]:.3f}s")
    print(f"  p99:  {sorted(ttfts)[int(len(ttfts)*0.99)]:.3f}s")
    print(f"  mean: {mean(ttfts):.3f}s")
    print(f"  min:  {min(ttfts):.3f}s")
    print(f"  max:  {max(ttfts):.3f}s")
    
    print(f"\n{'Full Latency Statistics':^70}")
    print(f"{'-'*70}")
    print(f"  p50:  {median(full_lat):.3f}s")
    print(f"  p95:  {sorted(full_lat)[int(len(full_lat)*0.95)]:.3f}s")
    print(f"  p99:  {sorted(full_lat)[int(len(full_lat)*0.99)]:.3f}s")
    print(f"  mean: {mean(full_lat):.3f}s")
    print(f"  min:  {min(full_lat):.3f}s")
    print(f"  max:  {max(full_lat):.3f}s")

    # Calculate throughput
    duration = max(r["end"] for r in results) - min(r["start"] for r in results)
    actual_duration = test_end - test_start
    throughput = len(successful) / duration if duration > 0 else 0
    
    print(f"\n{'Performance Metrics':^70}")
    print(f"{'-'*70}")
    print(f"Test duration:           {actual_duration:.2f}s")
    print(f"Request duration:        {duration:.2f}s")
    print(f"Throughput:              {throughput:.2f} req/s")
    print(f"Avg latency/request:     {duration/len(successful):.3f}s")
    print(f"{'='*70}\n")

    # Write results CSV to results directory
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)
    filename = os.path.join(results_dir, f"results_{run_tag}.csv")
    with open(filename, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "start", "first_token", "end", "status"])
        for r in results:
            writer.writerow([r["id"], r["start"], r["first_token"], r["end"], r["status"]])
    print(f"Saved results to: {filename}")
    
    # Save summary metadata
    meta_filename = os.path.join(results_dir, f"metadata_{run_tag}.txt")
    with open(meta_filename, "w") as f:
        f.write(f"run_tag={run_tag}\n")
        f.write(f"target={TARGET}\n")
        f.write(f"concurrency={concurrency}\n")
        f.write(f"requests_per_client={requests_per_client}\n")
        f.write(f"total_requests={len(results)}\n")
        f.write(f"successful_requests={len(successful)}\n")
        f.write(f"p50_ttft={median(ttfts):.3f}\n")
        f.write(f"p95_ttft={sorted(ttfts)[int(len(ttfts)*0.95)]:.3f}\n")
        f.write(f"p99_ttft={sorted(ttfts)[int(len(ttfts)*0.99)]:.3f}\n")
        f.write(f"throughput={throughput:.2f}\n")
        f.write(f"duration={duration:.2f}\n")
    print(f"Saved metadata to: {meta_filename}\n")


if __name__ == "__main__":
    main()