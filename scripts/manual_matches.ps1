<#
PowerShell wrapper to run try_run.py with short arguments.

Usage (from repo root):
  # first time: create and install venv (optional)
  .\scripts\setup_venv.ps1 -InstallEditable:$false

  # Run the bot (PowerShell)
  .\scripts\try-run.ps1 -mode queue -nBattles 1
  .\scripts\try-run.ps1 -mode accept
  .\scripts\try-run.ps1 -mode auto

Notes:
- The script forwards parameters to `python .\try_run.py` in the repo root.
- If you put the `scripts` folder on your PATH or create shortcuts, you can call this from anywhere.
#>

param(
    [int]$nBattles = 1
)

# Use the repo-local python if a .venv exists and is activated; otherwise the system python
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Join-Path $repoRoot ".."
$repoRoot = (Resolve-Path $repoRoot).Path

# If a .venv exists in repo root, prefer its python
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $python = $venvPython
} else {
    $python = "python"
}

Write-Host "Running manual_matches.py with mode=queue nBattles=$nBattles using: $python"
& $python "$repoRoot\manual_matches.py" --mode queue --n-battles $nBattles

# Return the exit code from the python process
exit $LASTEXITCODE
