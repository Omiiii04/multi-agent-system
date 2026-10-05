# PowerShell runner for Windows
$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# Locate Python in ML conda environment or fallback to python
$pyExe = "$env:USERPROFILE\.conda\envs\ML\python.exe"
if (-not (Test-Path $pyExe)) {
    $pyExe = (Get-Command python).Source
}

Write-Host "Using Python: $pyExe"
& $pyExe "$scriptDir\run_local.py"
