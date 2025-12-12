# ─────────────────────────────────────────────
# vllm_live_metrics.ps1
# Purpose: Live refresh of key vLLM metrics from /metrics endpoint
# ─────────────────────────────────────────────

$ProgressPreference = 'SilentlyContinue'
$metricsUrl = "http://localhost:8000/metrics"

# List of vLLM metrics you want to monitor
$queries = @(
    "vllm:num_requests_waiting",
    "vllm:num_requests_running",
    "vllm:num_requests_swapped",
    "vllm:gpu_cache_usage_perc",
    "vllm:num_preemptions_total"
)

Write-Host "Starting live vLLM metrics monitor..." -ForegroundColor Cyan
Write-Host "Press Ctrl + C to stop.`n" -ForegroundColor DarkGray

while ($true) {
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host ("[{0}]" -f $timestamp) -ForegroundColor Yellow

    # Fetch all metrics from the endpoint
    $resp = Invoke-RestMethod -Uri $metricsUrl

    foreach ($metric in $queries) {
        $line = ($resp -split "`n" | Where-Object { $_ -match "^$metric" }) | Select-Object -First 1
        if ($line) {
            $value = ($line -split " ")[-1]
            Write-Host ("{0} : {1}" -f $metric, $value)
        }
        else {
            Write-Host ("{0} : (no data)" -f $metric)
        }
    }

    Write-Host "==============================" -ForegroundColor DarkGray
    Start-Sleep -Seconds 2
}
