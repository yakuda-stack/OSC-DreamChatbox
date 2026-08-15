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

$artifacts        = @()
$iscc             = $null
$installerSkipped = $false

# ----------------------------------------------------------- 1) Installer
if (-not $SkipInstaller) {
    Write-Host "`n--- One-Folder-Build (Basis fuer den Installer) ---" -ForegroundColor Green
    # build-exe.ps1 wirft selbst bei Fehlern ($ErrorActionPreference = Stop),
    # $LASTEXITCODE stammt hier noch vom letzten externen Prozess und taugt
    # nicht als Erfolgsindikator - deshalb keine Abfrage darauf.
    & $Build -NoConsole -Clean @Deps

    # ab jetzt steht die venv - weitere Builds brauchen keine Deps mehr
    $Deps["SkipDeps"] = $true

    $iscc = $null

    # 1) im PATH?
    $cmd = Get-Command iscc -ErrorAction SilentlyContinue
    if ($cmd) { $iscc = $cmd.Source }

    # 2) Registry. Inno Setup ist eine 32-Bit-Anwendung, der Uninstall-Key
    #    liegt auf 64-Bit-Windows also unter WOW6432Node. Der Setup-Scope
    #    entscheidet zwischen HKLM (/ALLUSERS) und HKCU (per user).
    if (-not $iscc) {
        $roots = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
                   "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                   "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")
        foreach ($root in $roots) {
            foreach ($key in @("Inno Setup 7_is1", "Inno Setup 6_is1", "Inno Setup 5_is1")) {
                $loc = (Get-ItemProperty -Path (Join-Path $root $key) `
                        -Name InstallLocation -ErrorAction SilentlyContinue).InstallLocation
                if ($loc) {
                    $c = Join-Path $loc "ISCC.exe"
                    if (Test-Path $c) { $iscc = $c; break }
                }
            }
            if ($iscc) { break }
        }
    }

    # 3) uebliche Verzeichnisse, falls die Registry nichts hergibt
    if (-not $iscc) {
        foreach ($base in @("${env:ProgramFiles(x86)}", "$env:ProgramFiles",
                            "$env:LOCALAPPDATA\Programs")) {
            if (-not $base) { continue }
            foreach ($name in @("Inno Setup 7", "Inno Setup 6", "Inno Setup 5")) {
                $c = Join-Path $base "$name\ISCC.exe"
                if (Test-Path $c) { $iscc = $c; break }
            }
            if ($iscc) { break }
        }
    }

    if (-not $iscc) {
        Write-Host ""
        Write-Warning "ISCC.exe nicht gefunden - der Installer wird uebersprungen."
        Write-Host "Inno Setup installieren, dann make-release.ps1 -SkipDeps nochmal:" -ForegroundColor Yellow
        Write-Host "    winget install -e --id JRSoftware.InnoSetup" -ForegroundColor Yellow
        Write-Host "  oder https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
        Write-Host "Danach eine NEUE PowerShell oeffnen, damit PATH neu eingelesen wird." -ForegroundColor Yellow
        $installerSkipped = $true
    }
}

if ($iscc -and -not $SkipInstaller) {
    Write-Host "ISCC: $iscc" -ForegroundColor DarkGray

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
if ($installerSkipped) {
    Write-Warning "UNVOLLSTAENDIG: setup.exe fehlt, Inno Setup war nicht installiert."
    Write-Host "Das Release ist so nicht fertig - siehe die Meldung oben." -ForegroundColor Yellow
    exit 1
}
Write-Host "Auf die Release-Seite hochladen. Keinen ZIP des One-Folder-Builds" -ForegroundColor Yellow
Write-Host "anhaengen - daraus entsteht der _internal-DLL-Fehler."            -ForegroundColor Yellow
