$ErrorActionPreference = "Stop"
$base = "http://127.0.0.1:8400"

function Assert-That {
    param([bool]$Condition, [string]$Label)
    if ($Condition) {
        Write-Host "$Label : ok" -ForegroundColor Green
    } else {
        Write-Host "$Label : FAILED" -ForegroundColor Red
    }
}

function Expect-Status {
    param([scriptblock]$Attempt, [int]$Expected, [string]$Label)
    try {
        & $Attempt | Out-Null
        Write-Host "$Label : NOT REFUSED (expected $Expected)" -ForegroundColor Red
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq $Expected) {
            Write-Host "$Label : refused with HTTP $code" -ForegroundColor Green
        } else {
            Write-Host "$Label : HTTP $code (expected $Expected)" -ForegroundColor Red
        }
    }
}

function New-Material {
    param([string]$ProjectId, [hashtable]$Body)
    $json = $Body | ConvertTo-Json
    return Invoke-RestMethod -Method Post -Uri "$base/projects/$ProjectId/materials" -ContentType "application/json" -Body $json
}

function Get-Collection {
    param([string]$Uri)
    $raw = (curl.exe -s $Uri) -join "`n"
    return $raw | ConvertFrom-Json
}

$fixture = Join-Path $env:TEMP "bison-material-fixture"
if (Test-Path $fixture) { Remove-Item $fixture -Recurse -Force }

$repo = Join-Path $fixture "repo"
New-Item -ItemType Directory -Path (Join-Path $repo "src") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $repo "node_modules\junk") -Force | Out-Null

$mainPy = @'
import sys


def run():
    return 1


if __name__ == "__main__":
    run()
'@

Set-Content -Path (Join-Path $repo "src\main.py") -Value $mainPy
Set-Content -Path (Join-Path $repo "src\settings.py") -Value 'API_KEY = "a9F3kZ2qLp7XvB1nR4tY"'
Set-Content -Path (Join-Path $repo "package.json") -Value '{"dependencies":{"react":"^18"}}'
Set-Content -Path (Join-Path $repo "node_modules\junk\a.js") -Value 'junk'
Set-Content -Path (Join-Path $fixture "fake.png") -Value 'this is not an image'

Write-Host "fixture at $fixture"

$body = @{ name = "Materials"; goal = "exercise ingestion"; project_type = "code" } | ConvertTo-Json
$project = Invoke-RestMethod -Method Post -Uri "$base/projects" -ContentType "application/json" -Body $body
Write-Host "project $($project.id)"

$folder = New-Material -ProjectId $project.id -Body @{ kind = "folder"; source_path = $repo; caption = "the repo" }
Assert-That ($folder.kind -eq "folder") "folder material created"
Assert-That ($folder.size_bytes -gt 0) "size recorded"
Assert-That ($folder.content_hash.Length -eq 64) "content hash is sha256"
Assert-That (Test-Path $folder.path) "copy exists on disk"
Assert-That (-not (Test-Path (Join-Path $folder.path "node_modules"))) "node_modules was not copied"

$scan = Invoke-RestMethod -Uri "$base/materials/$($folder.id)/scan"
Assert-That ($scan.total_files -eq 3) "three files scanned"
Assert-That (@($scan.entry_points) -contains "repo/src/main.py") "entry point detected"
Assert-That (@($scan.skipped_directories) -contains "repo/node_modules") "prune recorded"
Assert-That (@($scan.dependency_manifests)[0].ecosystem -eq "npm") "npm manifest parsed"
Assert-That ($scan.truncated -eq $false) "not truncated"

$python = @($scan.languages) | Where-Object { $_.language -eq "python" }
Assert-That ($python.files -eq 2 -and $python.parsed -eq 2) "python files parsed by tree-sitter"

$findings = @($scan.secret_findings)
Assert-That ($findings.Count -eq 1) "one secret flagged"
Assert-That ($findings[0].kind -eq "assigned_api_key") "secret classified"
Assert-That ($findings[0].preview -notlike "*a9F3kZ2qLp7XvB1nR4tY*") "raw secret never stored"

$link = New-Material -ProjectId $project.id -Body @{ kind = "link"; url = "https://example.com/spec" }
Assert-That ($link.url -eq "https://example.com/spec") "link material created"
Assert-That ($null -eq $link.path) "link has no copy on disk"

Expect-Status -Label "scan of a link" -Expected 404 -Attempt {
    Invoke-RestMethod -Uri "$base/materials/$($link.id)/scan"
}
Expect-Status -Label "link without url" -Expected 422 -Attempt {
    New-Material -ProjectId $project.id -Body @{ kind = "link" }
}
Expect-Status -Label "folder without source_path" -Expected 422 -Attempt {
    New-Material -ProjectId $project.id -Body @{ kind = "folder" }
}
Expect-Status -Label "source that does not exist" -Expected 404 -Attempt {
    New-Material -ProjectId $project.id -Body @{ kind = "folder"; source_path = "C:\nope\missing" }
}
Expect-Status -Label "a file declared as a folder" -Expected 422 -Attempt {
    New-Material -ProjectId $project.id -Body @{ kind = "folder"; source_path = (Join-Path $repo "package.json") }
}
Expect-Status -Label "text renamed to .png" -Expected 422 -Attempt {
    New-Material -ProjectId $project.id -Body @{ kind = "image"; source_path = (Join-Path $fixture "fake.png") }
}
Expect-Status -Label "unknown material" -Expected 404 -Attempt {
    Invoke-RestMethod -Uri "$base/materials/does-not-exist"
}

$rescanned = Invoke-RestMethod -Method Post -Uri "$base/materials/$($folder.id)/rescan"
Assert-That (@($rescanned.skipped_directories) -contains "repo/node_modules") "rescan preserves the prune record"
Assert-That ($rescanned.total_files -eq 3) "rescan agrees with the first scan"

$listed = Get-Collection "$base/projects/$($project.id)/materials"
Assert-That ($listed.Count -eq 2) "two materials listed"

$events = Get-Collection "$base/projects/$($project.id)/events"
Assert-That ($events.Count -eq 4) "four events before deletion"
Assert-That (@($events | Where-Object { $_.event_type -eq "material.added" }).Count -eq 2) "two additions logged"
Assert-That (@($events | Where-Object { $_.event_type -eq "material.rescanned" }).Count -eq 1) "rescan logged"
Assert-That (@($events | Where-Object { $_.material_id }).Count -eq 3) "every material event carries its id"

$stored = $folder.path
Invoke-RestMethod -Method Delete -Uri "$base/materials/$($folder.id)" | Out-Null
Assert-That (-not (Test-Path $stored)) "copy removed from disk"

Expect-Status -Label "read a deleted material" -Expected 404 -Attempt {
    Invoke-RestMethod -Uri "$base/materials/$($folder.id)"
}

$events = Get-Collection "$base/projects/$($project.id)/events"
Assert-That ($events.Count -eq 5) "removal logged, refusals wrote nothing"

Write-Host "done" -ForegroundColor Cyan
