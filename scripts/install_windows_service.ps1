# ==============================================================================
# VYZN Netra - 1-Click Windows Background Service Installer for Billing PCs
# Deploys VYZN as a persistent background daemon on shopkeeper's Windows 10/11 PC.
# Runs silently without console window and starts automatically upon system reboot.
# ==============================================================================

param (
    [string]$SiteId = "site_local_default",
    [string]$CloudUrl = "https://fleet.vyzn.ai",
    [string]$SiteSecret = ""
)

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "VYZN NETRA - ZERO-HARDWARE EDGE SERVICE INSTALLER (WINDOWS)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    $VenvPython = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $VenvPython) {
        Write-Error "Python 3.10+ runtime not found. Please install Python from python.org before running installer."
        exit 1
    }
}

Write-Host "[OK] Using Python interpreter: $VenvPython" -ForegroundColor Green

# Create Launcher VBS to run python invisibly without keeping cmd window open
$LauncherVbs = Join-Path $ProjectRoot "scripts\run_silent.vbs"
$RunEdgePy = Join-Path $ProjectRoot "run_edge.py"

$VbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """$VenvPython"" ""$RunEdgePy""""", 0, False
"@

[System.IO.File]::WriteAllText($LauncherVbs, $VbsContent, [System.Text.Encoding]::UTF8)
Write-Host "[OK] Created silent background launcher: $LauncherVbs" -ForegroundColor Green

# Register Scheduled Task to start at system boot and user logon
$TaskName = "VYZN_Netra_Agent"
$Action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$LauncherVbs`""
$TriggerBoot = New-ScheduledTaskTrigger -AtStartup
$TriggerLogon = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Priority 7 -ExecutionTimeLimit (New-TimeSpan -Days 365)

try {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($TriggerBoot, $TriggerLogon) -Settings $Settings -Description "VYZN Netra AI Surveillance Background Agent"
    Write-Host "[OK] Successfully registered Windows background task: $TaskName" -ForegroundColor Green
    Write-Host "[OK] VYZN will now start automatically in the background on every system boot." -ForegroundColor Green
    Write-Host "[OK] Dynamic Resource Governor active: Low CPU priority during billing hours." -ForegroundColor Green
} catch {
    Write-Warning "Could not register scheduled task (run as Administrator for autostart registration)."
}
