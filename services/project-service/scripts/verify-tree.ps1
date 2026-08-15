$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8400"

function Send-Json {
    param([string]$Path, [hashtable]$Body)
    return Invoke-RestMethod -Method Post -Uri "$base$Path" -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 6)
}

function Get-Overall {
    param([string]$ProjectId)
    return (Invoke-RestMethod -Uri "$base/projects/$ProjectId/progress").overall
}

function Show-Progress {
    param([string]$ProjectId, [string]$Label)
    $overall = Get-Overall -ProjectId $ProjectId
    $pct = "{0,7:N2}" -f $overall.percentage
    Write-Host ("{0} %  [{1,2}/{2,2} weight]  {3}" -f $pct, $overall.verified_weight, $overall.counted_weight, $Label)
}

function Expect-Refusal {
    param([scriptblock]$Attempt, [string]$Label)
    try {
        & $Attempt | Out-Null
        Write-Host "$Label : NOT REFUSED" -ForegroundColor Red
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        Write-Host "$Label : refused with HTTP $code" -ForegroundColor Green
    }
}

$project = Send-Json -Path "/projects" -Body @{
    name         = "Fixture Tree"
    goal         = "prove the progress engine"
    project_type = "code"
}
Send-Json -Path "/projects/$($project.id)/activate" -Body @{ actor = "user" } | Out-Null
Write-Host "project $($project.id) active`n"

$root = Send-Json -Path "/projects/$($project.id)/tasks" -Body @{
    title = "Ship the service"; kind = "setup"; assigned_role = "user"; position = 0
}

$leaves = @{}
$names = @("Alpha", "Bravo", "Charlie", "Delta")

for ($i = 0; $i -lt $names.Count; $i++) {
    $leaf = Send-Json -Path "/projects/$($project.id)/tasks" -Body @{
        title = $names[$i]; kind = "code"; assigned_role = "engine"
        parent_id = $root.id; position = $i + 1
    }
    $criteria = @()
    1..5 | ForEach-Object {
        $criteria += Send-Json -Path "/tasks/$($leaf.id)/criteria" -Body @{
            statement = "$($names[$i]) criterion $_"; check_kind = "deterministic"; weight = 1
        }
    }
    $leaves[$names[$i]] = @{ task = $leaf; criteria = $criteria }
}

Write-Host "5 tasks, 20 criteria created`n"
Show-Progress -ProjectId $project.id -Label "baseline"

foreach ($criterion in $leaves["Alpha"].criteria) {
    Send-Json -Path "/criteria/$($criterion.id)/status" -Body @{ status = "verified"; actor = "inspector" } | Out-Null
    Show-Progress -ProjectId $project.id -Label "verified $($criterion.statement)"
}

Write-Host ""
Send-Json -Path "/tasks/$($leaves["Delta"].task.id)/state" -Body @{
    state = "ignored"; reason = "out of scope for this release"; actor = "user"
} | Out-Null
Show-Progress -ProjectId $project.id -Label "IGNORED Delta  (denominator shrinks, percentage rises)"

Send-Json -Path "/tasks/$($leaves["Charlie"].task.id)/state" -Body @{
    state = "skipped"; reason = "deferred to next sprint"; actor = "user"
} | Out-Null
Show-Progress -ProjectId $project.id -Label "SKIPPED Charlie  (denominator holds, percentage unchanged)"

Send-Json -Path "/criteria/$($leaves["Bravo"].criteria[0].id)/status" -Body @{
    status = "ignored"; reason = "check is not mechanisable here"; actor = "user"
} | Out-Null
Show-Progress -ProjectId $project.id -Label "IGNORED one Bravo criterion"

Send-Json -Path "/criteria/$($leaves["Bravo"].criteria[1].id)/status" -Body @{
    status = "failed"; reason = "endpoint returned 500"; actor = "inspector"
} | Out-Null
Show-Progress -ProjectId $project.id -Label "FAILED one Bravo criterion  (stays in denominator)"

Write-Host ""
Expect-Refusal -Label "move an ignored task straight to done" -Attempt {
    Send-Json -Path "/tasks/$($leaves["Delta"].task.id)/state" -Body @{ state = "done"; actor = "user" }
}
Expect-Refusal -Label "skip a task with no reason" -Attempt {
    Send-Json -Path "/tasks/$($leaves["Bravo"].task.id)/state" -Body @{ state = "skipped"; actor = "user" }
}
Expect-Refusal -Label "depend on a task that does not exist" -Attempt {
    Send-Json -Path "/projects/$($project.id)/tasks" -Body @{
        title = "Orphan"; kind = "code"; depends_on = @("11111111-1111-1111-1111-111111111111")
    }
}

Write-Host "`nper-task progress:"
$snapshot = Invoke-RestMethod -Uri "$base/projects/$($project.id)/progress"
@($snapshot.per_task) |
    ForEach-Object {
        [pscustomobject]@{
            task     = $_.task_id.Substring(0, 8)
            percent  = "{0:N2}" -f $_.percentage
            verified = $_.criteria_verified
            failed   = $_.criteria_failed
            ignored  = $_.criteria_ignored
            total    = $_.criteria_total
        }
    } | Format-Table -AutoSize

$events = @(Invoke-RestMethod -Uri "$base/projects/$($project.id)/events?limit=500")
Write-Host "ledger entries: $($events.Count)"
