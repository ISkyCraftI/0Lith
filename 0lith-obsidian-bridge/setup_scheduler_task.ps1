# setup_scheduler_task.ps1
# ========================
# Registers "0Lith Daily Planner" as a Windows Task Scheduler job.
#
# Behaviour:
#   - Runs scheduler.py every hour from 08:00 to 22:00 (15 executions/day)
#   - Only fires when the user is logged on (Interactive logon — no background ghosts)
#   - Logs stdout+stderr to logs\YYYY-Www.log (weekly rotation, ISO week numbers)
#   - Idempotent: safe to run multiple times, updates the existing task silently
#
# Prerequisites:
#   Python venv at .venv\Scripts\python.exe
#   Create with: python -m venv .venv && .venv\Scripts\pip install -r requirements.txt
#
# Usage (from 0lith-obsidian-bridge\):
#   .\setup_scheduler_task.ps1
#
# Verify:
#   Get-ScheduledTask -TaskName "0Lith Daily Planner"
#   Start-ScheduledTask -TaskName "0Lith Daily Planner"   # manual test run

$ErrorActionPreference = "Stop"

$TASK_NAME  = "0Lith Daily Planner"
$BRIDGE_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe  = Join-Path $BRIDGE_DIR ".venv\Scripts\python.exe"
$ScriptPath = Join-Path $BRIDGE_DIR "scheduler.py"
$LogDir     = Join-Path $BRIDGE_DIR "logs"

# ── Guards ────────────────────────────────────────────────────────────────────

if (-not (Test-Path $PythonExe)) {
    Write-Error @"
Python venv not found at: $PythonExe

Create it with:
  cd "$BRIDGE_DIR"
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
"@
    exit 1
}

if (-not (Test-Path $ScriptPath)) {
    Write-Error "scheduler.py not found at: $ScriptPath"
    exit 1
}

# ── Action ────────────────────────────────────────────────────────────────────
#
# Why powershell.exe as the executable?
# Task Scheduler has no native stdout/stderr redirection, and the log filename
# must be computed at execution time (weekly rotation). Using powershell.exe
# with an inline -Command block solves both problems cleanly.
#
# The -Command block (evaluated at task execution time, not at registration):
#   1. Ensures the logs\ directory exists
#   2. Computes the weekly log filename: YYYY-Www.log  (e.g. 2026-W10.log)
#   3. Runs scheduler.py, merges stdout+stderr into an array ($out)
#   4. Appends a timestamped block to the log file
#
# No embedded double-quotes in the inline command — avoids ArgumentList escaping
# issues entirely. Add-Content handles string arrays by writing one line per element.

$EscapedLogDir = $LogDir.Replace("'", "''")    # defensive: escape single quotes
$EscapedPython = $PythonExe.Replace("'", "''")
$EscapedScript = $ScriptPath.Replace("'", "''")

$InlineCmd = (
    "`$ld='$EscapedLogDir';" +
    "New-Item -Force -ItemType Directory -Path `$ld | Out-Null;" +
    "`$lf = Join-Path `$ld (Get-Date -UFormat '%Y-W%V.log');" +
    "`$ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss';" +
    "`$out = (& '$EscapedPython' '$EscapedScript' 2>&1);" +
    "Add-Content -Path `$lf -Value ('--- [' + `$ts + '] ---');" +
    "Add-Content -Path `$lf -Value `$out;" +
    "Add-Content -Path `$lf -Value ''"
)

$Action = New-ScheduledTaskAction `
    -Execute          "powershell.exe" `
    -Argument         "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -Command `"& { $InlineCmd }`"" `
    -WorkingDirectory $BRIDGE_DIR

# ── Trigger: every hour from 08:00 for 14 hours (08:00 through 22:00) ─────────

$Trigger = New-ScheduledTaskTrigger -Daily -At "08:00"
$Trigger.Repetition.Interval = "PT1H"   # repeat every 1 hour
$Trigger.Repetition.Duration = "PT14H"  # for 14 hours → last run at 22:00

# ── Principal: interactive session only ───────────────────────────────────────
#
# LogonType Interactive means the task will NOT run if no user is logged on.
# This avoids wasting resources on a locked/headless machine and keeps the
# vault access to sessions where Obsidian is actually running.
# No administrator privileges required for registration.

$Principal = New-ScheduledTaskPrincipal `
    -UserId    "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel  Limited

# ── Settings ──────────────────────────────────────────────────────────────────

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit      (New-TimeSpan -Minutes 10) `
    -MultipleInstances       IgnoreNew `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries

# MultipleInstances IgnoreNew: if a run is still active when the next trigger
# fires (e.g. TimeTree export hangs), the new execution is silently skipped
# rather than launched in parallel.

# ── Register (create or silently update if already exists) ────────────────────

$Task = New-ScheduledTask `
    -Action      $Action `
    -Trigger     $Trigger `
    -Principal   $Principal `
    -Settings    $Settings `
    -Description "0Lith Daily Planner — runs scheduler.py hourly from 08:00 to 22:00. Logs to logs\YYYY-Www.log."

Register-ScheduledTask -TaskName $TASK_NAME -InputObject $Task -Force | Out-Null

# ── Summary ───────────────────────────────────────────────────────────────────

Write-Host ""
Write-Host "[OK] Tache '$TASK_NAME' enregistree." -ForegroundColor Green
Write-Host "     Python  : $PythonExe"
Write-Host "     Script  : $ScriptPath"
Write-Host "     Planif. : toutes les heures de 08:00 a 22:00"
Write-Host "     Logs    : $LogDir\YYYY-Www.log"
Write-Host ""
Write-Host "Verification :"
Write-Host "  Get-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host ""
Write-Host "Test immediat :"
Write-Host "  Start-ScheduledTask -TaskName '$TASK_NAME'"
Write-Host "  Start-Sleep 5"
Write-Host "  Get-ChildItem '$LogDir'"
