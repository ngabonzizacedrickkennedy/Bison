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

function Get-Collection {
    param([string]$Uri)
    return ((curl.exe -s $Uri) -join "`n") | ConvertFrom-Json
}

function Save-Conceive {
    param([string]$ProjectId, [array]$Blocks)
    $json = @{ blocks = $Blocks } | ConvertTo-Json -Depth 10
    return Invoke-RestMethod -Method Put -Uri "$base/projects/$ProjectId/conceive" -ContentType "application/json" -Body $json
}

function New-Project {
    param([string]$Name)
    $body = @{ name = $Name; goal = "conceive fixture"; project_type = "code" } | ConvertTo-Json
    return Invoke-RestMethod -Method Post -Uri "$base/projects" -ContentType "application/json" -Body $body
}

$fixture = Join-Path $env:TEMP "bison-conceive-fixture"
if (Test-Path $fixture) { Remove-Item $fixture -Recurse -Force }
$repo = Join-Path $fixture "repo"
New-Item -ItemType Directory -Path (Join-Path $repo "src") -Force | Out-Null
Set-Content -Path (Join-Path $repo "src\main.py") -Value 'x = 1'

$project = New-Project -Name "Conceive"
$other = New-Project -Name "Referenced"
Write-Host "project $($project.id)"

$body = @{ kind = "folder"; source_path = $repo } | ConvertTo-Json
$material = Invoke-RestMethod -Method Post -Uri "$base/projects/$($project.id)/materials" -ContentType "application/json" -Body $body

$empty = Invoke-RestMethod -Uri "$base/projects/$($project.id)/conceive"
Assert-That ($empty.revision_number -eq 0) "a new project starts at revision zero"
Assert-That (@($empty.blocks).Count -eq 0) "and holds no blocks"

$blocks = @(
    @{ type = "markdown"; text = "Build a CLI" },
    @{ type = "link"; url = "https://example.com"; note = "reference" },
    @{ type = "project_ref"; project_id = $other.id },
    @{ type = "file_ref"; material_id = $material.id; path = "repo/src/main.py" }
)

$first = Save-Conceive -ProjectId $project.id -Blocks $blocks
Assert-That ($first.revision_number -eq 1) "first save creates revision one"
Assert-That (@($first.blocks).Count -eq 4) "all four block types stored"
Assert-That ((@($first.blocks)[0].id).Length -gt 0) "server assigned block ids"

$saved = @($first.blocks)
$again = Save-Conceive -ProjectId $project.id -Blocks $saved
Assert-That ($again.revision_number -eq 1) "an identical save mints no revision"

$edited = @($first.blocks | ForEach-Object { $_ | ConvertTo-Json -Depth 10 | ConvertFrom-Json })
$edited[0].text = "Build a CLI and a daemon"
$second = Save-Conceive -ProjectId $project.id -Blocks $edited
Assert-That ($second.revision_number -eq 2) "an edit creates revision two"

$reordered = @($edited[1], $edited[0], $edited[2], $edited[3])
$third = Save-Conceive -ProjectId $project.id -Blocks $reordered
Assert-That ($third.revision_number -eq 3) "reordering counts as a change"

$one = Invoke-RestMethod -Uri "$base/projects/$($project.id)/conceive/revisions/1"
Assert-That (@($one.blocks)[0].text -eq "Build a CLI") "revision one still reads as written"

$current = Invoke-RestMethod -Uri "$base/projects/$($project.id)/conceive"
Assert-That (@($current.blocks)[0].type -eq "link") "current revision reflects the reorder"

$revisions = Get-Collection "$base/projects/$($project.id)/conceive/revisions"
Assert-That ($revisions.Count -eq 3) "three revisions listed"
Assert-That ((@($revisions) | Select-Object -ExpandProperty revision_number) -join "," -eq "1,2,3") "numbered in order"

Expect-Status -Label "a revision that does not exist" -Expected 404 -Attempt {
    Invoke-RestMethod -Uri "$base/projects/$($project.id)/conceive/revisions/99"
}
Expect-Status -Label "an unknown block type" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "video"; url = "https://example.com" })
}
Expect-Status -Label "empty markdown" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "markdown"; text = "" })
}
Expect-Status -Label "duplicate block ids" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(
        @{ id = "same"; type = "markdown"; text = "a" },
        @{ id = "same"; type = "markdown"; text = "b" }
    )
}
Expect-Status -Label "a conceive referencing its own project" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "project_ref"; project_id = $project.id })
}
Expect-Status -Label "a reference to a project that does not exist" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "project_ref"; project_id = "nope" })
}
Expect-Status -Label "a material belonging to another project" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $other.id -Blocks @(@{ type = "file_ref"; material_id = $material.id; path = "repo/src/main.py" })
}
Expect-Status -Label "a file that is not in the material" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "file_ref"; material_id = $material.id; path = "repo/absent.py" })
}
Expect-Status -Label "a path escaping its material" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "file_ref"; material_id = $material.id; path = "..\..\..\Windows\win.ini" })
}
Expect-Status -Label "a folder used as an image" -Expected 422 -Attempt {
    Save-Conceive -ProjectId $project.id -Blocks @(@{ type = "image"; material_id = $material.id })
}

$revisions = Get-Collection "$base/projects/$($project.id)/conceive/revisions"
Assert-That ($revisions.Count -eq 3) "no refusal minted a revision"

$events = Get-Collection "$base/projects/$($project.id)/events"
Assert-That (@($events | Where-Object { $_.event_type -eq "conceive.saved" }).Count -eq 3) "three saves logged"
Assert-That ($events.Count -eq 5) "ledger holds project, material and three saves"

Write-Host "done" -ForegroundColor Cyan
