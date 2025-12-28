<#
Setup script to create a .venv in the repository root, activate it (for the current shell),
upgrade pip/setuptools/wheel, install requirements, and optionally install the project editable.

This script will explicitly run the commands you requested:
- python -m venv .venv
- .venv\Scripts\Activate.ps1 (dot-source to keep activation in this session)
- python -m pip install --upgrade pip setuptools wheel
- python -m pip install -r requirements.txt (if present)
- python -m pip install -e . (if requested)

Usage (PowerShell, run from repo root or provide -RepoRoot):
  # Create .venv and install requirements (no editable install)
  .\scripts\setup_venv.ps1 -InstallEditable:$false

  # Create .venv and also install the project in editable mode
  .\scripts\setup_venv.ps1 -InstallEditable:$true

Parameters:
  -RepoRoot: optional path to repository root. If not provided the script infers it.
  -InstallEditable: whether to run `pip install -e .` (default: $false)
  -InstallRequirements: whether to install requirements.txt if present (default: $true)
  -Recreate: if $true will remove an existing .venv and recreate it (default: $false)

Notes on activation:
  - After running this script, your current PowerShell session will be using the repo .venv python.
  - To manually activate later, run: .\.venv\Scripts\Activate.ps1
#>

param(
    [string]$RepoRoot = "",
    [bool]$InstallEditable = $false,
    [bool]$InstallRequirements = $true,
    [bool]$Recreate = $false
)

if (-not $RepoRoot) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot = Join-Path $scriptDir ".."
    $RepoRoot = (Resolve-Path $RepoRoot).Path
}

Write-Host "Repo root: $RepoRoot"

$venvPath = Join-Path $RepoRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"
$activateScript = Join-Path $venvPath "Scripts\Activate.ps1"

if (Test-Path $venvPath -and $Recreate) {
    Write-Host "Recreating .venv (removing existing)..."
    Remove-Item -Recurse -Force $venvPath
}

if (-not (Test-Path $pythonPath)) {
    Write-Host "Creating virtual environment at $venvPath..."
    # Use system python to create the venv
    python -m venv $venvPath
} else {
    Write-Host ".venv already exists. Skipping creation."
}

if (-not (Test-Path $activateScript)) {
    Write-Warning "Activation script not found at $activateScript — venv may not have been created correctly."
} else {
    Write-Host "Activating .venv in this session..."
    # dot-source the Activate.ps1 to keep activation in the current session
    . $activateScript
}

# Ensure pip/setuptools/wheel are available/upgraded inside the venv
if (-not (Test-Path $pythonPath)) {
    Write-Error "Python executable not found at $pythonPath — aborting pip install steps."
    exit 1
}

Write-Host "Upgrading pip, setuptools and wheel inside the venv..."
& $pythonPath -m pip install --upgrade pip setuptools wheel

if ($InstallRequirements) {
    $reqFile = Join-Path $RepoRoot "requirements.txt"
    if (Test-Path $reqFile) {
        Write-Host "Installing requirements from requirements.txt..."
        & $pythonPath -m pip install -r $reqFile
    } else {
        Write-Host "No requirements.txt found at $reqFile — skipping."
    }
} else {
    Write-Host "InstallRequirements is false — skipping requirements installation."
}

if ($InstallEditable) {
    Write-Host "Installing package in editable mode (pip install -e .)..."
    & $pythonPath -m pip install -e $RepoRoot
}

Write-Host "Setup complete. To activate the venv later run: .\\.venv\\Scripts\\Activate.ps1"
