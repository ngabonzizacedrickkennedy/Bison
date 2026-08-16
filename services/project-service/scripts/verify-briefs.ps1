$ErrorActionPreference = 'Stop'

$base = 'http://127.0.0.1:8400'
$failures = 0
$checks = 0

function Check {
    param([string]$Label, [scriptblock]$Condition)

    $script:checks++

    if (& $Condition) {
        Write-Host "  ok    $Label" -ForegroundColor Green
    }
    else {
        Write-Host "  FAIL  $Label" -ForegroundColor Red
        $script:failures++
    }
}

function Refuses {
    param([string]$Label, [string]$Path, [hashtable]$Body, [int]$Status)

    $script:checks++

    try {
        Invoke-RestMethod "$base$Path" -Method Post -Body ($Body | ConvertTo-Json) -ContentType 'application/json' | Out-Null
        Write-Host "  FAIL  $Label (was accepted)" -ForegroundColor Red
        $script:failures++
    }
    catch {
        $actual = [int]$_.Exception.Response.StatusCode

        if ($actual -eq $Status) {
            Write-Host "  ok    $Label ($Status)" -ForegroundColor Green
        }
        else {
            Write-Host "  FAIL  $Label (expected $Status, got $actual)" -ForegroundColor Red
            $script:failures++
        }
    }
}

function Get-Json {
    param([string]$Path)

    return (curl.exe -s "$base$Path" | ConvertFrom-Json)
}

Write-Host "`nsetup" -ForegroundColor Cyan

$project = Invoke-RestMethod "$base/projects" -Method Post -ContentType 'application/json' -Body (@{
    name = "brief-fixture-$(Get-Random -Maximum 99999)"
    goal = 'verify brief rounds and clarification answers'
    project_type = 'code'
} | ConvertTo-Json)

$id = $project.id
Write-Host "  project $id"

$blank = curl.exe -s "$base/projects/$id/brief"
Check 'a project with no brief returns null' { $blank.Trim() -eq 'null' }

$none = Get-Json "/projects/$id/clarifications"
Check 'a project with no clarifications returns empty' { @($none).Count -eq 0 }

Write-Host "`nround one" -ForegroundColor Cyan

$body = @{
    conceive_revision_number = 0
    summary = 'first reading'
    interpreted_goal = 'match invoices to payments'
    project_type = 'code'
    confidence = 0.5
    unresolved_fields = @('target_environment')
    contradictions = @('offline versus hosted')
    model_id = 'fixture/model'
    prompt_version = 'v3'
    prompt_hash = 'a' * 64
    clarify = $true
    blocking = $true
    reasons = @('confidence below threshold')
    questions = @(
        @{ text = 'Local or hosted?'; why_asked = 'the constraint conflicts'; answer_kind = 'choice'; choices = @('local', 'hosted') },
        @{ text = 'What is out of scope?'; why_asked = 'to bound the work'; answer_kind = 'text'; choices = $null },
        @{ text = 'Proceed without a UI?'; why_asked = 'to confirm the shape'; answer_kind = 'confirm'; choices = $null }
    )
}

$one = Invoke-RestMethod "$base/projects/$id/briefs" -Method Post -Body ($body | ConvertTo-Json -Depth 6) -ContentType 'application/json'

Check 'first brief is round one' { $one.round -eq 1 }
Check 'brief keeps its model and prompt hash' { $one.model_id -eq 'fixture/model' -and $one.prompt_version -eq 'v3' }
Check 'brief keeps its contradictions' { @($one.contradictions).Count -eq 1 }

$clar = @(Get-Json "/projects/$id/clarifications")
Check 'one clarification request exists' { $clar.Count -eq 1 }
Check 'the request is blocking' { $clar[0].blocking -eq $true }
Check 'three questions were stored' { @($clar[0].questions).Count -eq 3 }
Check 'questions keep their order' { @($clar[0].questions)[0].position -eq 0 }
Check 'why_asked survived' { @($clar[0].questions)[0].why_asked -eq 'the constraint conflicts' }
Check 'nothing is answered yet' { @(@($clar[0].questions) | Where-Object { $_.answered }).Count -eq 0 }
Check 'the request is not closed' { $null -eq $clar[0].answered_at }

Write-Host "`nrefusals" -ForegroundColor Cyan

$questions = @($clar[0].questions)
$choiceId = ($questions | Where-Object { $_.answer_kind -eq 'choice' }).id
$textId = ($questions | Where-Object { $_.answer_kind -eq 'text' }).id
$confirmId = ($questions | Where-Object { $_.answer_kind -eq 'confirm' }).id

Refuses 'prose sent to a choice question' "/questions/$choiceId/answer" @{ text_value = 'local' } 422
Refuses 'an unlisted choice' "/questions/$choiceId/answer" @{ choice = 'carrier pigeon' } 422
Refuses 'an empty text answer' "/questions/$textId/answer" @{ text_value = '  ' } 422
Refuses 'prose sent to a confirm question' "/questions/$confirmId/answer" @{ text_value = 'yes' } 422
Refuses 'an unknown question' '/questions/00000000-0000-0000-0000-000000000000/answer' @{ text_value = 'x' } 404

$after = @(Get-Json "/projects/$id/clarifications")
Check 'refusals wrote nothing' { @(@($after[0].questions) | Where-Object { $_.answered }).Count -eq 0 }

Write-Host "`nanswers" -ForegroundColor Cyan

Invoke-RestMethod "$base/questions/$choiceId/answer" -Method Post -ContentType 'application/json' -Body (@{ choice = 'local' } | ConvertTo-Json) | Out-Null
Invoke-RestMethod "$base/questions/$textId/answer" -Method Post -ContentType 'application/json' -Body (@{ text_value = 'no UI, no tax' } | ConvertTo-Json) | Out-Null

$partial = @(Get-Json "/projects/$id/clarifications")
Check 'two of three answered' { @(@($partial[0].questions) | Where-Object { $_.answered }).Count -eq 2 }
Check 'the request stays open while one remains' { $null -eq $partial[0].answered_at }

$reply = Invoke-RestMethod "$base/questions/$confirmId/answer" -Method Post -ContentType 'application/json' -Body (@{ confirmed = $false } | ConvertTo-Json)
Check 'a false confirm is accepted' { $reply.confirmed -eq $false }

$closed = @(Get-Json "/projects/$id/clarifications")
Check 'the request closes when nothing remains' { $null -ne $closed[0].answered_at }
Check 'a false confirm reads as no' { (@($closed[0].questions) | Where-Object { $_.answer_kind -eq 'confirm' }).answer -eq 'no' }
Check 'the choice answer is readable' { (@($closed[0].questions) | Where-Object { $_.answer_kind -eq 'choice' }).answer -eq 'local' }

Write-Host "`nchanging an answer" -ForegroundColor Cyan

Invoke-RestMethod "$base/questions/$choiceId/answer" -Method Post -ContentType 'application/json' -Body (@{ choice = 'hosted' } | ConvertTo-Json) | Out-Null

$revised = @(Get-Json "/projects/$id/clarifications")
Check 'the answer was replaced, not appended' { @(@($revised[0].questions) | Where-Object { $_.answered }).Count -eq 3 }
Check 'the new value is stored' { (@($revised[0].questions) | Where-Object { $_.answer_kind -eq 'choice' }).answer -eq 'hosted' }

Write-Host "`nround two" -ForegroundColor Cyan

$body.confidence = 0.95
$body.summary = 'second reading'
$body.unresolved_fields = @()
$body.contradictions = @()
$body.clarify = $false
$body.blocking = $false
$body.reasons = @()
$body.questions = @()

$two = Invoke-RestMethod "$base/projects/$id/briefs" -Method Post -Body ($body | ConvertTo-Json -Depth 6) -ContentType 'application/json'

Check 'second brief is round two' { $two.round -eq 2 }

$latest = Get-Json "/projects/$id/brief"
Check 'latest returns the newest round' { $latest.round -eq 2 -and $latest.summary -eq 'second reading' }

$all = @(Get-Json "/projects/$id/briefs")
Check 'both rounds are kept' { $all.Count -eq 2 }
Check 'round one is unchanged' { $all[0].summary -eq 'first reading' -and $all[0].confidence -eq 0.5 }

$still = @(Get-Json "/projects/$id/clarifications")
Check 'a resolved round adds no request' { $still.Count -eq 1 }

Write-Host "`nledger" -ForegroundColor Cyan

$events = @(Get-Json "/projects/$id/events")
Check 'brief.created was recorded twice' { @($events | Where-Object { $_.event_type -eq 'brief.created' }).Count -eq 2 }
Check 'clarification.requested was recorded once' { @($events | Where-Object { $_.event_type -eq 'clarification.requested' }).Count -eq 1 }
Check 'every answer was recorded' { @($events | Where-Object { $_.event_type -eq 'clarification.answered' }).Count -eq 4 }

Write-Host "`ncleanup" -ForegroundColor Cyan

Invoke-RestMethod "$base/projects/$id/archive" -Method Post -ContentType 'application/json' -Body (@{ reason = 'fixture' } | ConvertTo-Json) | Out-Null
Write-Host "  archived $id"

Write-Host "`n$($checks - $failures) of $checks checks passed" -ForegroundColor $(if ($failures -eq 0) { 'Green' } else { 'Red' })

if ($failures -gt 0) { exit 1 }
