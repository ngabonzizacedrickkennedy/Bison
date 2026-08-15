$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8400"

function New-Project {
    param([string]$Name, [string]$Goal)
    $body = @{ name = $Name; goal = $Goal; project_type = "code" } | ConvertTo-Json
    return Invoke-RestMethod -Method Post -Uri "$base/projects" -ContentType "application/json" -Body $body
}

function Move-Project {
    param([string]$Id, [string]$Action, [string]$Reason)
    $body = @{ reason = $Reason; actor = "user" } | ConvertTo-Json
    return Invoke-RestMethod -Method Post -Uri "$base/projects/$Id/$Action" -ContentType "application/json" -Body $body
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

$alpha = New-Project -Name "Alpha" -Goal "first project"
$beta = New-Project -Name "Beta" -Goal "second project"
Write-Host "created alpha=$($alpha.id) beta=$($beta.id)"

Move-Project -Id $alpha.id -Action "activate" -Reason "start" | Out-Null
$beta = Move-Project -Id $beta.id -Action "activate" -Reason "switch"
$alpha = Invoke-RestMethod -Uri "$base/projects/$($alpha.id)"
Write-Host "after switch: alpha=$($alpha.state) beta=$($beta.state)"

$beta = Move-Project -Id $beta.id -Action "archive" -Reason "done"
Write-Host "beta archived at $($beta.archived_at)"

Expect-Refusal -Label "pause an archived project" -Attempt {
    Move-Project -Id $beta.id -Action "pause" -Reason "illegal"
}

$fillers = @()
1..9 | ForEach-Object { $fillers += (New-Project -Name "Filler $_" -Goal "capacity test") }

$listing = Invoke-RestMethod -Uri "$base/projects"
Write-Host "open projects: $($listing.open_projects) of $($listing.max_projects)"

Expect-Refusal -Label "eleventh open project" -Attempt {
    New-Project -Name "Overflow" -Goal "should never exist"
}

foreach ($filler in $fillers) {
    Move-Project -Id $filler.id -Action "archive" -Reason "capacity test cleanup" | Out-Null
}

$listing = Invoke-RestMethod -Uri "$base/projects"
Write-Host "open projects after cleanup: $($listing.open_projects) of $($listing.max_projects)"

Write-Host "`nevent ledger for alpha:"
$events = @(Invoke-RestMethod -Uri "$base/projects/$($alpha.id)/events")
$events |
    ForEach-Object {
        [pscustomobject]@{
            event  = $_.event_type
            from   = $_.from_state
            to     = $_.to_state
            reason = $_.reason
        }
    } |
    Format-Table -AutoSize
