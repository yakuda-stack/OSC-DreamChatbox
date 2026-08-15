<#
    make-release.ps1 - baut die beiden Artefakte, die auf die Release-Seite
    gehoeren, und sonst nichts:

        dist\OSC-DreamChatbox-<ver>-setup.exe       <- Installer (Standard)
        dist\OSC-DreamChatbox-<ver>-portable.exe    <- eine einzelne Datei

    Der rohe One-Folder-Build wird NICHT mehr als ZIP verteilt. Genau der
    ist die Ursache fuer "Failed to load Python DLL ... \_internal\pythonXXX.dll":
    Nutzer ziehen die .exe aus dem ZIP heraus, lassen _internal liegen, und
    der PyInstaller-Bootloader stirbt, bevor auch nur eine Zeile Python
    laeuft - man kann das im Code nicht abfangen.

    Aufruf:

        .\packaging\windows\make-release.ps1
        .\packaging\windows\make-release.ps1 -SkipPortable
        .\packaging\windows\make-release.ps1 -SkipDeps      # schnelle Rebuilds

    Voraussetzung zusaetzlich zu build-exe.ps1: Inno Setup 6 (iscc.exe).
    https://jrsoftware.org/isdl.php
#>

[CmdletBinding()]
param(
    [switch]$SkipPortable,   # nur den Installer bauen
    [switch]$SkipInstaller,  # nur die portable .exe bauen
    [switch]$SkipDeps        # Build-venv unangetastet lassen
)

$ErrorActionPreference = "Stop"

$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptDir "..\..")
Set-Location $ProjectRoot

$Version = (Select-String -Path "core\constants.py" `
            -Pattern '^VERSION\s*=\s*"v?([^"]+)"').Matches[0].Groups[1].Value
Write-Host "=== OSC-DreamChatbox $Version - Release-Build ===" -ForegroundColor Cyan

$Build = Join-Path $ScriptDir "build-exe.ps1"
$Iss   = Join-Path $ScriptDir "installer.iss"
$Dist  = Join-Path $ProjectRoot "dist"
# NICHT  $Deps = if ($SkipDeps) { @("-SkipDeps") } else { @() }
# Ein leeres Array aus einem if-Statement wird beim Zuweisen aufgeloest und
# landet als $null in der Variablen. @Deps splattet dann ein literales $null
# als Positionsparameter -> "Es wurde kein Positionsparameter gefunden, der
# das Argument "$null" akzeptiert." Eine Hashtable hat das Problem nicht.
$Deps = @{}
if ($SkipDeps) { $Deps["SkipDeps"] = $true }

$artifacts = @()

# ----------------------------------------------------------- 1) Installer
if (-not $SkipInstaller) {
    Write-Host "`n--- One-Folder-Build (Basis fuer den Installer) ---" -ForegroundColor Green
    # build-exe.ps1 wirft selbst bei Fehlern ($ErrorActionPreference = Stop),
    # $LASTEXITCODE stammt hier noch vom letzten externen Prozess und taugt
    # nicht als Erfolgsindikator - deshalb keine Abfrage darauf.
    & $Build -NoConsole -Clean @Deps

    # ab jetzt steht die venv - weitere Builds brauchen keine Deps mehr
    $Deps["SkipDeps"] = $true

    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if (-not $iscc) {
        foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                         "$env:ProgramFiles\Inno Setup 6\ISCC.exe")) {
            if (Test-Path $c) { $iscc = $c; break }
        }
    }
    if (-not $iscc) {
        throw "iscc.exe nicht gefunden. Inno Setup 6 installieren: https://jrsoftware.org/isdl.php"
    }

    Write-Host "`n--- Inno Setup ---" -ForegroundColor Green
    # Version per /D reinreichen, damit die .iss nicht gegen constants.py driftet
    & $iscc "/DAppVersion=$Version" $Iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup fehlgeschlagen" }

    $setup = Join-Path $Dist "OSC-DreamChatbox-$Version-setup.exe"
    if (Test-Path $setup) { $artifacts += $setup }
}

# ------------------------------------------------------------ 2) Portable
if (-not $SkipPortable) {
    # Windows erlaubt keine Datei "dist\OSC-DreamChatbox.exe" neben einem
    # Ordner "dist\OSC-DreamChatbox" - der One-Folder-Build muss also weg,
    # bevor PyInstaller den One-File-Build dorthin schreibt.
    $folder = Join-Path $Dist "OSC-DreamChatbox"
    if (Test-Path $folder -PathType Container) {
        Write-Host "`n--- One-Folder-Build aufraeumen (steckt jetzt im Installer) ---" -ForegroundColor Yellow
        Remove-Item -Recurse -Force $folder
    }

    Write-Host "`n--- One-File-Build (portable) ---" -ForegroundColor Green
    & $Build -NoConsole -OneFile @Deps

    $src = Join-Path $Dist "OSC-DreamChatbox.exe"
    $dst = Join-Path $Dist "OSC-DreamChatbox-$Version-portable.exe"
    if (-not (Test-Path $src)) { throw "$src nicht gefunden" }
    Move-Item -Force $src $dst
    $artifacts += $dst
}

# -------------------------------------------------------------- Ergebnis
Write-Host "`n=== Release-Artefakte ===" -ForegroundColor Cyan
foreach ($a in $artifacts) {
    $mb = [math]::Round((Get-Item $a).Length / 1MB, 1)
    Write-Host ("  {0,-52} {1,6} MB" -f (Split-Path -Leaf $a), $mb) -ForegroundColor Green
}
Write-Host ""
Write-Host "Beides auf die Release-Seite hochladen. Keinen ZIP des One-Folder-" -ForegroundColor Yellow
Write-Host "Builds anhaengen - daraus entsteht der _internal-DLL-Fehler."      -ForegroundColor Yellow
