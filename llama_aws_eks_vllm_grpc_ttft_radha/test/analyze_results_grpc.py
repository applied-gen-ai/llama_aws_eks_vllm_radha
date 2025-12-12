#!/usr/bin/env python3
"""
analyze_results_grpc.py
----------------------------------------
Purpose:
Analyze CSV result files from client_measure_ttft_grpc.py.
Computes TTFT/latency stats, throughput, GPU utilization correlation, and draws plots.

Usage:
python analyze_results_grpc.py <results_dir>

Example:
python analyze_results_grpc.py ./results/
"""
import os
import re
import sys
import pandas as pd
import matplotlib.pyplot as plt
from statistics import mean, median


def extract_params(filename):
    """Extract max_inflight and concurrency from filename like results_mi350_c16.csv"""
    mi_match = re.search(r'mi(\d+)', filename)
    c_match = re.search(r'c(\d+)', filename)
    mi = int(mi_match.group(1)) if mi_match else None
    c = int(c_match.group(1)) if c_match else None
    return mi, c


def parse_gpu_log(log_path):
    """Parse nvidia-smi dmon output and return average GPU utilization."""
    if not os.path.exists(log_path):
        return None, None
    
    try:
        # Read the log file, skip comment lines
        with open(log_path, 'r') as f:
            lines = [l.strip() for l in f if l.strip() and not l.startswith('#')]
        
        if not lines:
            return None, None
        
        # Parse header to find column indices
        header = lines[0].split()
        try:
            sm_idx = header.index('sm')
            mem_idx = header.index('mem')
        except ValueError:
            print(f"[WARNING] Could not find 'sm' or 'mem' columns in {log_path}")
            return None, None
        
        # Parse data rows
        gpu_utils = []
        mem_utils = []
        for line in lines[1:]:
            parts = line.split()
            if len(parts) > max(sm_idx, mem_idx):
                try:
                    gpu_utils.append(float(parts[sm_idx]))
                    mem_utils.append(float(parts[mem_idx]))
                except ValueError:
                    continue
        
        if gpu_utils and mem_utils:
            return mean(gpu_utils), mean(mem_utils)
        return None, None
    except Exception as e:
        print(f"[WARNING] Failed parsing {log_path}: {e}")
        return None, None


def analyze_single_file(filename):
    """
    Analyze a single CSV file and generate statistics.
    """
    try:
        df = pd.read_csv(filename)
    except Exception as e:
        print(f"[ERROR] Failed to read {filename}: {e}")
        return None

    # Filter out failed requests
    df_success = df[df["first_token"].notna()].copy()
    
    if len(df_success) == 0:
        print(f"[ERROR] File: {filename} - No successful requests found.")
        return None

    # Compute metrics
    df_success["ttft"] = df_success["first_token"] - df_success["start"]
    df_success["latency"] = df_success["end"] - df_success["start"]
    
    total_reqs = len(df)
    success_reqs = len(df_success)
    
    duration = df_success["end"].max() - df_success["start"].min()
    throughput = success_reqs / duration if duration > 0 else 0

    summary = {
        "file": os.path.basename(filename),
        "total_reqs": total_reqs,
        "success_reqs": success_reqs,
        "p50_ttft": df_success["ttft"].median(),
        "p95_ttft": df_success["ttft"].quantile(0.95),
        "p99_ttft": df_success["ttft"].quantile(0.99),
        "mean_ttft": mean(df_success["ttft"]),
        "min_ttft": df_success["ttft"].min(),
        "max_ttft": df_success["ttft"].max(),
        "p50_lat": df_success["latency"].median(),
        "p95_lat": df_success["latency"].quantile(0.95),
        "mean_lat": mean(df_success["latency"]),
        "throughput": throughput,
        "duration": duration,
    }

    return summary, df_success


def plot_individual_file(filename, df_success, summary, results_dir):
    """Generate plots for a single run."""
    base_filename = os.path.basename(filename).replace(".csv", "")
    
    # TTFT histogram
    plt.figure(figsize=(10, 6))
    plt.hist(df_success["ttft"], bins=30, color='steelblue', alpha=0.8, edgecolor='black')
    plt.axvline(summary["p50_ttft"], color='red', linestyle='--', linewidth=2, 
                label=f'p50: {summary["p50_ttft"]:.3f}s')
    plt.axvline(summary["p95_ttft"], color='orange', linestyle='--', linewidth=2, 
                label=f'p95: {summary["p95_ttft"]:.3f}s')
    plt.axvline(summary["mean_ttft"], color='green', linestyle='--', linewidth=2, 
                label=f'mean: {summary["mean_ttft"]:.3f}s')
    plt.title(f"TTFT Distribution: {base_filename}", fontsize=14, fontweight='bold')
    plt.xlabel("TTFT (seconds)", fontsize=12)
    plt.ylabel("Count", fontsize=12)
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f"{base_filename}_ttft_hist.png"), dpi=150)
    plt.close()

    # Latency histogram
    plt.figure(figsize=(10, 6))
    plt.hist(df_success["latency"], bins=30, color='orange', alpha=0.8, edgecolor='black')
    plt.axvline(summary["p50_lat"], color='red', linestyle='--', linewidth=2, 
                label=f'p50: {summary["p50_lat"]:.3f}s')
    plt.axvline(summary["p95_lat"], color='purple', linestyle='--', linewidth=2, 
                label=f'p95: {summary["p95_lat"]:.3f}s')
    plt.title(f"Full Latency Distribution: {base_filename}", fontsize=14, fontweight='bold')
    plt.xlabel("Latency (seconds)", fontsize=12)
    plt.ylabel("Count", fontsize=12)
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f"{base_filename}_latency_hist.png"), dpi=150)
    plt.close()

    # TTFT timeline
    plt.figure(figsize=(12, 6))
    df_sorted = df_success.sort_values('start')
    plt.plot(df_sorted["start"] - df_sorted["start"].min(), 
             df_sorted["ttft"], 
             marker='o', markersize=3, linestyle='-', linewidth=1, alpha=0.6)
    plt.axhline(summary["p50_ttft"], color='red', linestyle='--', linewidth=2, 
                label=f'p50: {summary["p50_ttft"]:.3f}s')
    plt.axhline(summary["p95_ttft"], color='orange', linestyle='--', linewidth=2, 
                label=f'p95: {summary["p95_ttft"]:.3f}s')
    plt.title(f"TTFT Over Time: {base_filename}", fontsize=14, fontweight='bold')
    plt.xlabel("Time from start (seconds)", fontsize=12)
    plt.ylabel("TTFT (seconds)", fontsize=12)
    plt.legend(fontsize=10)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, f"{base_filename}_ttft_timeline.png"), dpi=150)
    plt.close()


def generate_comparison_plots(summaries_df, results_dir):
    """Generate comparison plots across multiple runs."""
    
    # Group by max_inflight and concurrency
    if 'max_inflight' not in summaries_df.columns or 'concurrency' not in summaries_df.columns:
        print("[INFO] No max_inflight/concurrency pattern found. Skipping comparison plots.")
        return
    
    summaries_df = summaries_df.sort_values(by=["concurrency", "max_inflight"])
    
    # Plot 1: TTFT (p95) vs Throughput trade-off
    plt.figure(figsize=(10, 7))
    for conc, group in summaries_df.groupby("concurrency"):
        plt.plot(group["throughput"], group["p95_ttft"], 
                marker="o", markersize=8, label=f"concurrency={conc}", linewidth=2)
    plt.title("TTFT (p95) vs Throughput Trade-off", fontsize=14, fontweight='bold')
    plt.xlabel("Throughput (req/s)", fontsize=12)
    plt.ylabel("TTFT p95 (seconds)", fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "tradeoff_ttft_vs_throughput.png"), dpi=150)
    plt.close()
    print(f"  Saved: tradeoff_ttft_vs_throughput.png")

    # Plot 2: p50/p95 TTFT vs max_inflight
    plt.figure(figsize=(10, 7))
    for conc, group in summaries_df.groupby("concurrency"):
        plt.plot(group["max_inflight"], group["p50_ttft"], 
                marker="o", linestyle="--", label=f"p50, c={conc}")
        plt.plot(group["max_inflight"], group["p95_ttft"], 
                marker="x", linestyle="-", label=f"p95, c={conc}")
    plt.title("TTFT vs max_inflight", fontsize=14, fontweight='bold')
    plt.xlabel("max_inflight", fontsize=12)
    plt.ylabel("TTFT (seconds)", fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "ttft_vs_maxinflight.png"), dpi=150)
    plt.close()
    print(f"  Saved: ttft_vs_maxinflight.png")

    # Plot 3: Throughput vs max_inflight
    plt.figure(figsize=(10, 7))
    for conc, group in summaries_df.groupby("concurrency"):
        plt.plot(group["max_inflight"], group["throughput"], 
                marker="o", markersize=8, label=f"concurrency={conc}", linewidth=2)
    plt.title("Throughput vs max_inflight", fontsize=14, fontweight='bold')
    plt.xlabel("max_inflight", fontsize=12)
    plt.ylabel("Throughput (req/s)", fontsize=12)
    plt.grid(True, alpha=0.3)
    plt.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(os.path.join(results_dir, "throughput_vs_maxinflight.png"), dpi=150)
    plt.close()
    print(f"  Saved: throughput_vs_maxinflight.png")

    # Plot 4: GPU Utilization vs TTFT (if GPU data available)
    if 'gpu_util' in summaries_df.columns and summaries_df['gpu_util'].notna().any():
        plt.figure(figsize=(10, 7))
        for conc, group in summaries_df.groupby("concurrency"):
            valid = group[group['gpu_util'].notna()]
            if not valid.empty:
                plt.plot(valid["gpu_util"], valid["p95_ttft"], 
                        marker="o", markersize=8, label=f"concurrency={conc}", linewidth=2)
        plt.title("TTFT (p95) vs GPU Utilization", fontsize=14, fontweight='bold')
        plt.xlabel("GPU Utilization (%)", fontsize=12)
        plt.ylabel("TTFT p95 (seconds)", fontsize=12)
        plt.axvline(x=85, color='green', linestyle='--', alpha=0.5, label='Optimal ~85%')
        plt.grid(True, alpha=0.3)
        plt.legend(fontsize=10)
        plt.tight_layout()
        plt.savefig(os.path.join(results_dir, "ttft_vs_gpu_util.png"), dpi=150)
        plt.close()
        print(f"  Saved: ttft_vs_gpu_util.png")


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_results_grpc.py <results_dir>")
        print("Example: python analyze_results_grpc.py ./results/")
        sys.exit(1)

    results_dir = sys.argv[1]
    
    if not os.path.isdir(results_dir):
        print(f"[ERROR] Directory not found: {results_dir}")
        sys.exit(1)

    csv_files = [f for f in os.listdir(results_dir) if f.startswith("results_") and f.endswith(".csv")]
    
    if not csv_files:
        print(f"[ERROR] No results_*.csv files found in {results_dir}")
        sys.exit(1)

    print(f"\n{'='*70}")
    print(f"{'Analyzing Load Test Results':^70}")
    print(f"{'='*70}\n")
    print(f"Found {len(csv_files)} result files\n")

    all_summaries = []
    
    for csv_file in sorted(csv_files):
        csv_path = os.path.join(results_dir, csv_file)
        print(f"Processing: {csv_file}")
        
        result = analyze_single_file(csv_path)
        if result is None:
            continue
        
        summary, df_success = result
        
        # Extract parameters from filename
        mi, c = extract_params(csv_file)
        summary["max_inflight"] = mi
        summary["concurrency"] = c
        
        # Try to parse GPU metrics
        gpu_log = os.path.join(results_dir, csv_file.replace("results_", "gpu_metrics_").replace(".csv", ".log"))
        gpu_util, mem_util = parse_gpu_log(gpu_log)
        summary["gpu_util"] = gpu_util
        summary["mem_util"] = mem_util
        
        all_summaries.append(summary)
        
        # Print summary
        print(f"  Total requests:      {summary['total_reqs']}")
        print(f"  Successful:          {summary['success_reqs']}")
        print(f"  TTFT p50/p95/p99:    {summary['p50_ttft']:.3f}s / {summary['p95_ttft']:.3f}s / {summary['p99_ttft']:.3f}s")
        print(f"  Throughput:          {summary['throughput']:.2f} req/s")
        if gpu_util:
            print(f"  GPU utilization:     {gpu_util:.1f}%")
        
        # Generate individual plots
        plot_individual_file(csv_path, df_success, summary, results_dir)
        print(f"  Generated plots for {csv_file}\n")
    
    # Create comparison DataFrame
    df_summary = pd.DataFrame(all_summaries)
    
    # Save summary CSV
    summary_csv = os.path.join(results_dir, "summary_all_runs.csv")
    df_summary.to_csv(summary_csv, index=False)
    print(f"Saved summary to: {summary_csv}\n")
    
    # Generate comparison plots
    print("Generating comparison plots...")
    generate_comparison_plots(df_summary, results_dir)
    
    # Print comparison table
    print(f"\n{'='*70}")
    print(f"{'Summary Table':^70}")
    print(f"{'='*70}")
    print(f"{'File':<30} {'TTFT p95':>10} {'Throughput':>12} {'GPU %':>8}")
    print(f"{'-'*70}")
    for _, row in df_summary.iterrows():
        gpu_str = f"{row['gpu_util']:.1f}" if pd.notna(row['gpu_util']) else "N/A"
        print(f"{row['file']:<30} {row['p95_ttft']:>9.3f}s {row['throughput']:>10.2f} r/s {gpu_str:>8}")
    print(f"{'='*70}\n")
    
    print("Analysis complete!")


if __name__ == "__main__":
    main()