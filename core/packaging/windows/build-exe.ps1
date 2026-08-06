<#
    build-exe.ps1 - OSC-DreamChatbox Windows builder

    Creates a build venv, installs the dependencies, converts the icon
    and runs PyInstaller with packaging/windows/osc-dreamchatbox.spec.

    Usage (PowerShell, from anywhere inside the project):

        .\packaging\windows\build-exe.ps1              # test build:
                                                       # one folder + console
        .\packaging\windows\build-exe.ps1 -OneFile     # single .exe
        .\packaging\windows\build-exe.ps1 -NoConsole   # release look
        .\packaging\windows\build-exe.ps1 -Clean       # wipe build/ + dist/

    If PowerShell refuses to run the script, allow local scripts once:
        Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#>

[CmdletBinding()]
param(
    [switch]$OneFile,     # single .exe instead of a folder
    [switch]$NoConsole,   # hide the console window
    [switch]$Clean,       # remove build/ and dist/ first
    [switch]$SkipDeps     # reuse the venv as-is (faster re-builds)
)

$ErrorActionPreference = "Stop"

# ------------------------------------------------------------ locate root
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $ProjectRoot

if (-not (Test-Path "osc_dreamchatbox.py")) {
    throw "osc_dreamchatbox.py not found in $ProjectRoot - wrong folder?"
}

$Version = (Select-String -Path "core\constants.py" -Pattern '^VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
Write-Host "=== OSC-DreamChatbox $Version - Windows build ===" -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot"

# ------------------------------------------------------------- python
$Py = "py"
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) { $Py = "python" }
if (-not (Get-Command $Py -ErrorAction SilentlyContinue)) {
    throw "No Python found. Install Python 3.11+ from python.org and tick 'Add to PATH'."
}
& $Py --version

# ------------------------------------------------------------- clean
if ($Clean) {
    Write-Host "[0/4] Cleaning build\ and dist\ ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

# --------------------------------------------------------------- venv
$VenvDir = ".build-venv"
$VenvPy  = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "[1/4] Creating build venv in $VenvDir ..." -ForegroundColor Green
    & $Py -m venv $VenvDir
} else {
    Write-Host "[1/4] Reusing build venv in $VenvDir" -ForegroundColor Green
}

if (-not $SkipDeps) {
    Write-Host "[2/4] Installing dependencies ..." -ForegroundColor Green
    & $VenvPy -m pip install --upgrade pip --quiet
    & $VenvPy -m pip install -r requirements-windows.txt
} else {
    Write-Host "[2/4] -SkipDeps: leaving the venv untouched" -ForegroundColor Green
}

# --------------------------------------------------------------- icon
# PyInstaller wants a .ico on Windows; build one from assets\icon.png once
$Ico = "assets\icon.ico"
$Png = "assets\icon.png"
if ((-not (Test-Path $Ico)) -and (Test-Path $Png)) {
    Write-Host "[3/4] Converting $Png -> $Ico ..." -ForegroundColor Green
    $conv = @"
from PIL import Image
img = Image.open(r'$Png').convert('RGBA')
img.save(r'$Ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon.ico written')
"@
    $conv | & $VenvPy -
} else {
    Write-Host "[3/4] Icon: $Ico already present (or no PNG to convert)" -ForegroundColor Green
}

# ------------------------------------------------------------ build
$env:DCB_ONEFILE = if ($OneFile)   { "1" } else { "0" }
$env:DCB_CONSOLE = if ($NoConsole) { "0" } else { "1" }

Write-Host "[4/4] Running PyInstaller (onefile=$($env:DCB_ONEFILE), console=$($env:DCB_CONSOLE)) ..." -ForegroundColor Green
& $VenvPy -m PyInstaller --noconfirm --clean `
    "packaging\windows\osc-dreamchatbox.spec"

if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

# ----------------------------------------------------------- report
Write-Host ""
Write-Host "=== Build finished ===" -ForegroundColor Cyan
if ($OneFile) {
    $out = "dist\OSC-DreamChatbox.exe"
} else {
    $out = "dist\OSC-DreamChatbox\OSC-DreamChatbox.exe"
}
if (Test-Path $out) {
    $sizeMb = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "Executable: $out  ($sizeMb MB)" -ForegroundColor Green
    Write-Host "Start it with:  .\$out"
} else {
    Write-Warning "Expected $out but it is not there - check the PyInstaller output above."
}
Write-Host "Config folder: $env:APPDATA\OSC-DreamChatbox"
