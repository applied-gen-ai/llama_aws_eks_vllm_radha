# ─────────────────────────────────────────────
# prometheus_live_monitor.ps1
# Purpose: Display selected Prometheus metrics live in the terminal
# ─────────────────────────────────────────────


# Step 2 – Allow PowerShell to run scripts (only if blocked)
### Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser


# Disable the default blue progress bar
$ProgressPreference = 'SilentlyContinue'

Write-Host "Starting live Prometheus metrics monitor..." -ForegroundColor Cyan
Write-Host "Press Ctrl + C to stop.`n" -ForegroundColor DarkGray

while ($true) {
    $queries = "llm_requests_in_flight","llm_request_queue_length","DCGM_FI_DEV_GPU_UTIL"

    # Timestamp header
    $timestamp = Get-Date -Format "HH:mm:ss"
    Write-Host ("[{0}]" -f $timestamp) -ForegroundColor Cyan

    foreach ($q in $queries) {
        $url = "http://localhost:9090/api/v1/query?query=$q"
        $resp = Invoke-RestMethod -Uri $url
        if ($resp.data.result.Count -gt 0) {
            $val = $resp.data.result[0].value[1]
            Write-Host ("{0} : {1}" -f $q, $val)
        }
        else {
            Write-Host ("{0} : (no data)" -f $q)
        }
    }

    Write-Host "==============" -ForegroundColor DarkGray
    Start-Sleep -Seconds 2
}
