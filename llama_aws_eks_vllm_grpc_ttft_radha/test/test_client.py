import os
import sys
import grpc
from dotenv import load_dotenv

# Make sure Python can see your generated stubs
sys.path.insert(0, r"E:\llama_aws_eks_vllm_gRPC_radha\docker")
from llm_grpc import llm_pb2 as pb, llm_pb2_grpc as pbg

load_dotenv()
TARGET = os.getenv("LLM_TARGET")

DEFAULT_TARGET = TARGET
print(f"ExternalIP is {DEFAULT_TARGET}")
TARGET = os.environ.get("LLM_TARGET", DEFAULT_TARGET)

OPTS = [
    ("grpc.keepalive_time_ms", 30000),
    ("grpc.keepalive_timeout_ms", 10000),
    ("grpc.http2.max_pings_without_data", 0),
    ("grpc.max_send_message_length", 50 * 1024 * 1024),
    ("grpc.max_receive_message_length", 50 * 1024 * 1024),
]


def main():
    print(f"[client] connecting to {TARGET} ...")
    channel = grpc.insecure_channel(TARGET, options=OPTS)
    grpc.channel_ready_future(channel).result(timeout=70)

    stub = pbg.LLMStub(channel)

    try:
        responses = stub.StreamGenerate(
            pb.GenerateRequest(
                prompt="What is the meaning of Legerdemain?",
                max_new_tokens=32,
                temperature=0.7,
            ),
            timeout=30,
        )

        print("REPLY:", end=" ", flush=True)

        # Use while loop to fetch tokens one by one
        while True:
            try:
                token = next(responses)  # get next streamed message
            except StopIteration:
                break  # no more tokens
            if token.is_last:
                break
            print(token.text, end="", flush=True)

        print()  # final newline

    except grpc.RpcError as e:
        print("[client] RPC failed")
        print("  code   :", e.code())
        print("  details:", e.details())
        if hasattr(e, "debug_error_string"):
            print("  debug  :", e.debug_error_string())
        raise
    finally:
        channel.close()


if __name__ == "__main__":
    main()

