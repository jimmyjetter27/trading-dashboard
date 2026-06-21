$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$bundledPy = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$pythonLabel = $null
$pythonArgs = @()

function Test-Mt5Import {
    param(
        [string]$Exe,
        [string[]]$Args = @()
    )
    try {
        $null = & $Exe @Args -c "import MetaTrader5" 2>$null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

if (Test-Path -LiteralPath $bundledPy -and (Test-Mt5Import -Exe $bundledPy)) {
    $pythonLabel = "Bundled Python"
    $pythonArgs = @($bundledPy)
}

$local313 = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
if (-not $pythonArgs.Count -and (Test-Path -LiteralPath $local313) -and (Test-Mt5Import -Exe $local313)) {
    $pythonLabel = "Local Python 3.13"
    $pythonArgs = @($local313)
}

if (-not $pythonArgs.Count -and (Get-Command py -ErrorAction SilentlyContinue)) {
    if (Test-Mt5Import -Exe "py" -Args @("-3.13")) {
        $pythonLabel = "Python launcher 3.13"
        $pythonArgs = @("py", "-3.13")
    } elseif (Test-Mt5Import -Exe "py" -Args @("-3.12")) {
        $pythonLabel = "Python launcher 3.12"
        $pythonArgs = @("py", "-3.12")
    }
}

if (-not $pythonArgs.Count -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $pathPython = (Get-Command python).Source
    if (Test-Mt5Import -Exe $pathPython) {
        $pythonLabel = "PATH Python"
        $pythonArgs = @($pathPython)
    }
}

if (-not $pythonArgs.Count -and (Test-Path -LiteralPath $bundledPy)) {
    $pythonLabel = "Bundled Python (MetaTrader5 missing)"
    $pythonArgs = @($bundledPy)
}

if (-not $pythonArgs.Count) {
    Write-Host "Python was not found. Install Python or add it to PATH, then run this app again."
    exit 1
}

Write-Host "Starting MetaTrader Trade Observer..."
Write-Host "Keep this window open while you use the dashboard."
Write-Host "Then open http://127.0.0.1:8765 in your browser."
Write-Host "Using Python: $pythonLabel"
Write-Host "Command: $($pythonArgs -join ' ') server.py"
if ($pythonArgs.Count -gt 1) {
    & $pythonArgs[0] $pythonArgs[1..($pythonArgs.Count - 1)] server.py
} else {
    & $pythonArgs[0] server.py
}
exit $LASTEXITCODE
