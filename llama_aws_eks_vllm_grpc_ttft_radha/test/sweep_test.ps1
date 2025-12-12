# sweep_test.ps1
$RESULTS_DIR = ".\results\sweep_qv"

# Create results directory
New-Item -ItemType Directory -Force -Path $RESULTS_DIR | Out-Null

# Test configurations
$INFLIGHT_VALUES = @(200, 300, 350, 400, 450, 512)
$CONCURRENCY_VALUES = @(50, 100, 200, 300, 400)

Write-Host "`n========================================"
Write-Host "Starting Load Test Sweep"
Write-Host "========================================`n"

foreach ($MI in $INFLIGHT_VALUES) {
    Write-Host "Testing MAX_INFLIGHT=$MI" -ForegroundColor Yellow
    
    foreach ($CONC in $CONCURRENCY_VALUES) {
        Write-Host "  Concurrency=$CONC" -ForegroundColor Green
        
        $RUN_TAG = "mi${MI}_c${CONC}"
        
        python test/client_measure_ttft_grpc.py $CONC 20 "Write a story about AI" 128 $RUN_TAG
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host "    [WARNING] Test failed" -ForegroundColor Red
        }
        
        Write-Host "    Cooling down..."
        Start-Sleep -Seconds 30
    }
}

Write-Host "`n========================================"
Write-Host "Analyzing results..."
Write-Host "========================================`n"

python analyze_results_grpc.py $RESULTS_DIR
