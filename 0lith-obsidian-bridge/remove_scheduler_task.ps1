# remove_scheduler_task.ps1
# ==========================
# Removes the "0Lith Daily Planner" Windows Task Scheduler job.
# Log files in logs\ are intentionally preserved.
#
# Usage (from 0lith-obsidian-bridge\):
#   .\remove_scheduler_task.ps1

$TASK_NAME = "0Lith Daily Planner"

$task = Get-ScheduledTask -TaskName $TASK_NAME -ErrorAction SilentlyContinue
if (-not $task) {
    Write-Host "Tache '$TASK_NAME' introuvable — rien a supprimer." -ForegroundColor Yellow
    exit 0
}

Unregister-ScheduledTask -TaskName $TASK_NAME -Confirm:$false

Write-Host "[OK] Tache '$TASK_NAME' supprimee." -ForegroundColor Green
Write-Host "     Les fichiers logs\ sont conserves."
