<#
PowerShell wrapper to run bot_matches.py with short arguments.

Usage (from repo root):
  .\scripts\bot-matches.ps1 -mode auto
  .\scripts\bot-matches.ps1 -mode queue -nBattles 3

The script prefers a repo-local .venv if present.
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("auto","queue","accept")]
    [string]$mode = "auto",

    [int]$nBattles = 1
)

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Join-Path $repoRoot ".."
$repoRoot = (Resolve-Path $repoRoot).Path

$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Running bot_matches.py with mode=$mode nBattles=$nBattles using: $python"
& $python "$repoRoot\bot_matches.py" --mode $mode --n-battles $nBattles
exit $LASTEXITCODE
