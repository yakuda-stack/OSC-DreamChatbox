<#
    dreamtemp-helper.ps1 - OSC-DreamChatbox temperature helper (Windows)

    Runs ELEVATED, started by the "Enable advanced temperature
    monitoring" button on the Hardware card. Polls every temperature
    source that an administrator can reach WITHOUT a kernel driver and
    writes them to a small JSON file the (unelevated) app reads.

    Sources, best first:
      1. root/LibreHardwareMonitor  - LHM's own WMI namespace. Present
         when LHM runs; this is the accurate CPU die temperature,
         because LHM has the signed driver we deliberately do not ship.
      2. root/OpenHardwareMonitor   - same for the older OHM.
      3. root/WMI MSAcpi_ThermalZoneTemperature - firmware ACPI thermal
         zones. Needs elevation but no driver. Common on laptops and OEM
         boards, usually absent on enthusiast desktop boards.

    Written by design:
      * exits on its own when the main app is gone (-ParentPid), so a
        stray elevated process cannot outlive the chatbox
      * exits when the app drops a stop file
      * writes atomically (temp file + move) so the app never reads half
        a JSON document
      * touches nothing outside the output file - no registry, no
        services, no drivers, no installs

    Parameters are always supplied by the app; the defaults only exist
    so you can run it by hand for debugging:

        powershell -ExecutionPolicy Bypass -File dreamtemp-helper.ps1 `
                   -OutFile "$env:APPDATA\OSC-DreamChatbox\temps.json" -Debug1
#>

param(
    [string]$OutFile   = "$env:APPDATA\OSC-DreamChatbox\temps.json",
    [string]$StopFile  = "$env:APPDATA\OSC-DreamChatbox\helper\stop",
    [int]   $ParentPid = 0,
    [int]   $IntervalMs = 1000,
    [switch]$Debug1
)

$ErrorActionPreference = "SilentlyContinue"

function Write-Line($msg) { if ($Debug1) { Write-Host $msg } }

# ---------------------------------------------------------------- LHM/OHM
function Get-HwMonitorTemps {
    foreach ($ns in @("root/LibreHardwareMonitor", "root/OpenHardwareMonitor")) {
        $sensors = Get-CimInstance -Namespace $ns -ClassName Sensor `
                   -ErrorAction SilentlyContinue |
                   Where-Object { $_.SensorType -eq "Temperature" }
        if (-not $sensors) { continue }

        $cpu = $null; $cpuScore = -1
        $gpu = $null; $gpuScore = -1
        foreach ($s in $sensors) {
            $v = [double]$s.Value
            if ($v -le 0 -or $v -ge 150) { continue }
            $name = "$($s.Name)".ToLower()
            $path = "$($s.Identifier)".ToLower()

            if ($path -like "*gpu*" -or $name -like "*gpu*") {
                # "GPU Core" is the die temp; "GPU Hot Spot" runs ~15 K
                # hotter and would look alarming in a chatbox
                $score = 1
                if ($name -like "*core*") { $score = 3 }
                elseif ($name -like "*hot*") { $score = 0 }
                if ($score -gt $gpuScore) { $gpuScore = $score; $gpu = $v }
            }
            elseif ($path -like "*cpu*" -or $name -like "*cpu*" -or
                    $name -like "*core*" -or $name -like "*tctl*") {
                $score = 1
                if ($name -like "*tctl*" -or $name -like "*tdie*" -or
                    $name -like "*package*") { $score = 3 }
                elseif ($name -like "*average*") { $score = 2 }
                elseif ($name -like "*max*")     { $score = 0 }
                if ($score -gt $cpuScore) { $cpuScore = $score; $cpu = $v }
            }
        }
        if ($null -ne $cpu -or $null -ne $gpu) {
            $short = ($ns -split "/")[-1]
            return @{ cpu = $cpu; gpu = $gpu; source = "wmi:$short" }
        }
    }
    return $null
}

# ------------------------------------------------------------------ ACPI
function Get-AcpiTemp {
    $zones = Get-CimInstance -Namespace "root/WMI" `
             -ClassName MSAcpi_ThermalZoneTemperature `
             -ErrorAction SilentlyContinue
    if (-not $zones) { return $null }
    $best = $null
    foreach ($z in $zones) {
        if ($null -eq $z.CurrentTemperature) { continue }
        # CurrentTemperature is in tenths of a KELVIN
        $c = [math]::Round(($z.CurrentTemperature / 10.0) - 273.15, 1)
        if ($c -le 0 -or $c -ge 150) { continue }
        # several zones can exist (CPU, chipset, skin) - the hottest one
        # is the closest thing to a package temperature ACPI offers
        if ($null -eq $best -or $c -gt $best) { $best = $c }
    }
    if ($null -eq $best) { return $null }
    return @{ cpu = $best; gpu = $null; source = "acpi" }
}

# ----------------------------------------------------------------- write
function Write-Temps($data) {
    $payload = [ordered]@{
        # NOT Get-Date -UFormat %s: that is timezone-affected in
        # PowerShell 5.1, and the app would judge every reading as
        # hours old and discard it. Compute the epoch explicitly.
        ts     = [math]::Round(([datetime]::UtcNow - [datetime]"1970-01-01").TotalSeconds, 3)
        cpu    = $data.cpu
        gpu    = $data.gpu
        source = $data.source
    }
    $json = $payload | ConvertTo-Json -Compress
    $dir = Split-Path -Parent $OutFile
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$OutFile.tmp"
    # atomic-ish: never let the app read a half-written file
    # PowerShell 5.1 puts a BOM in front of -Encoding UTF8 output;
    # the app therefore reads this file as utf-8-sig.
    Set-Content -Path $tmp -Value $json -Encoding UTF8 -Force
    Move-Item -Path $tmp -Destination $OutFile -Force
    Write-Line "wrote $json"
}

# ------------------------------------------------------------------ main
Write-Line "helper started (parent=$ParentPid, out=$OutFile)"
if (Test-Path $StopFile) { Remove-Item $StopFile -Force }

$idleRounds = 0
while ($true) {
    # 1. the app is gone -> we go too. Prevents an orphaned admin process.
    if ($ParentPid -gt 0) {
        if (-not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) {
            Write-Line "parent gone, exiting"
            break
        }
    }
    # 2. the app asked us to stop
    if (Test-Path $StopFile) {
        Write-Line "stop file present, exiting"
        Remove-Item $StopFile -Force
        break
    }

    $data = Get-HwMonitorTemps
    if ($null -eq $data) { $data = Get-AcpiTemp }

    if ($null -ne $data) {
        $idleRounds = 0
        Write-Temps $data
    } else {
        $idleRounds++
        # Nothing readable at all. Keep running (LHM may be started
        # later) but back off so we are not asking WMI every second
        # forever on a board that will never answer.
        if ($idleRounds -eq 15) {
            Write-Line "no source found - backing off to 10s polls"
        }
        if ($idleRounds -ge 15) { Start-Sleep -Seconds 10; continue }
    }

    Start-Sleep -Milliseconds $IntervalMs
}

Write-Line "helper finished"
