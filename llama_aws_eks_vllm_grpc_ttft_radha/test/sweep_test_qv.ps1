# quick_sweep.ps1
$RESULTS_DIR = ".\results\sweep_qv"
New-Item -ItemType Directory -Force -Path $RESULTS_DIR | Out-Null

# Reduced test matrix
$INFLIGHT_VALUES = @(300, 400, 500)   # Only 3 values
$CONCURRENCY_VALUES = @(300, 400, 500) # Only 3 values

Write-Host "`n========================================"
Write-Host "Starting Quick Test Sweep (9 tests)"
Write-Host "========================================`n"

foreach ($MI in $INFLIGHT_VALUES) {
    Write-Host "Testing MAX_INFLIGHT=$MI" -ForegroundColor Yellow
    
    foreach ($CONC in $CONCURRENCY_VALUES) {
        Write-Host "  Concurrency=$CONC" -ForegroundColor Green
        
        $RUN_TAG = "mi${MI}_c${CONC}"
        
        # Reduced requests: 10 instead of 20
        python test/client_measure_ttft_grpc.py $CONC 10 "Write a story about AI" 128 $RUN_TAG
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    [WARNING] Test failed" -ForegroundColor Red
        }
        
        Write-Host "    Cooling down..."
        Start-Sleep -Seconds 15  # Shorter cooldown
    }
}

Write-Host "`n========================================"
Write-Host "Analyzing results..."
Write-Host "========================================`n"

python test/analyze_results_grpc.py $RESULTS_DIR
