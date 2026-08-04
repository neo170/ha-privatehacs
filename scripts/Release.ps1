[CmdletBinding(SupportsShouldProcess)]
param(
    [ValidateSet("Patch", "Minor", "Major")]
    [string]$Bump = "Patch",

    [ValidatePattern("^\d+\.\d+\.\d+$")]
    [string]$Version,

    [string]$Repository = "neo170/ha-privatehacs",

    [string]$Branch = "main",

    [switch]$Prerelease
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-Tool {
    param(
        [Parameter(Mandatory)]
        [string]$File,

        [string[]]$Arguments = @()
    )

    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $File $($Arguments -join ' ')"
    }
}

function Get-ToolOutput {
    param(
        [Parameter(Mandatory)]
        [string]$File,

        [string[]]$Arguments = @()
    )

    $output = & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $File $($Arguments -join ' ')"
    }

    return ($output | Out-String).Trim()
}

function Set-Utf8FileContent {
    param(
        [Parameter(Mandatory)]
        [string]$Path,

        [Parameter(Mandatory)]
        [string]$Content
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Get-BumpedVersion {
    param(
        [Parameter(Mandatory)]
        [Version]$CurrentVersion,

        [Parameter(Mandatory)]
        [string]$Kind
    )

    switch ($Kind) {
        "Major" { return [Version]::new($CurrentVersion.Major + 1, 0, 0) }
        "Minor" { return [Version]::new($CurrentVersion.Major, $CurrentVersion.Minor + 1, 0) }
        default { return [Version]::new($CurrentVersion.Major, $CurrentVersion.Minor, $CurrentVersion.Build + 1) }
    }
}

foreach ($tool in "git", "gh", "py", "node") {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "Required command was not found: $tool"
    }
}

$repositoryRoot = Get-ToolOutput git @("rev-parse", "--show-toplevel")
Push-Location $repositoryRoot
try {
    $currentBranch = Get-ToolOutput git @("branch", "--show-current")
    if ($currentBranch -ne $Branch) {
        throw "Releases must be created from '$Branch', not '$currentBranch'."
    }

    $manifestPath = Join-Path $repositoryRoot "custom_components/privatehacs/manifest.json"
    $projectPath = Join-Path $repositoryRoot "pyproject.toml"
    $manifest = Get-Content -Raw $manifestPath | ConvertFrom-Json
    $projectContent = Get-Content -Raw $projectPath
    $projectVersionMatch = [regex]::Match($projectContent, '(?m)^version = "(?<version>[^"]+)"\s*$')
    if (-not $projectVersionMatch.Success -or $manifest.version -ne $projectVersionMatch.Groups["version"].Value) {
        throw "manifest.json and pyproject.toml do not have the same version."
    }

    $currentVersion = [Version]$manifest.version
    $releaseVersion = if ($Version) { [Version]$Version } else { Get-BumpedVersion $currentVersion $Bump }
    if ($releaseVersion -le $currentVersion) {
        throw "The release version ($releaseVersion) must be greater than the current version ($currentVersion)."
    }

    $tag = "v$releaseVersion"
    if ($WhatIfPreference) {
        Write-Host "WhatIf: would create $tag from $Branch and include all non-ignored changes in its commit."
        Invoke-Tool py @("-3", "-m", "pytest")
        Invoke-Tool node @("--check", "custom_components/privatehacs/frontend/privatehacs-panel.js")
        Invoke-Tool git @("diff", "--check")
        return
    }

    Invoke-Tool gh @("auth", "status")
    Invoke-Tool git @("fetch", "origin", $Branch, "--tags")
    $aheadBehind = (Get-ToolOutput git @("rev-list", "--left-right", "--count", "HEAD...origin/$Branch")) -split "\s+"
    if ($aheadBehind.Count -ne 2 -or $aheadBehind[1] -ne "0") {
        throw "origin/$Branch contains commits that are not in the local branch. Pull and resolve them before releasing."
    }

    & git ls-remote --exit-code --tags origin "refs/tags/$tag" *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "The tag $tag already exists on origin."
    }
    if ($LASTEXITCODE -ne 2) {
        throw "Could not verify whether $tag already exists on origin."
    }

    $manifestContent = Get-Content -Raw $manifestPath
    $manifestContent = [regex]::Replace(
        $manifestContent,
        '"version"\s*:\s*"[^"]+"',
        '"version": "' + $releaseVersion + '"',
        1
    )
    Set-Utf8FileContent $manifestPath $manifestContent

    $projectContent = [regex]::Replace(
        $projectContent,
        '(?m)^version = "[^"]+"\s*$',
        'version = "' + $releaseVersion + '"',
        1
    )
    Set-Utf8FileContent $projectPath $projectContent

    Invoke-Tool py @("-3", "-m", "pytest")
    Invoke-Tool node @("--check", "custom_components/privatehacs/frontend/privatehacs-panel.js")
    Invoke-Tool git @("diff", "--check")

    Invoke-Tool git @("add", "--all")
    & git diff --cached --quiet
    if ($LASTEXITCODE -eq 0) {
        throw "There are no changes to release."
    }
    if ($LASTEXITCODE -ne 1) {
        throw "Could not inspect staged changes."
    }

    Invoke-Tool git @("commit", "-m", "Release $tag")
    Invoke-Tool git @("push", "origin", $Branch)

    $commit = Get-ToolOutput git @("rev-parse", "HEAD")
    $releaseArguments = @(
        "release", "create", $tag,
        "--repo", $Repository,
        "--target", $commit,
        "--title", $tag,
        "--generate-notes"
    )
    if ($Prerelease) {
        $releaseArguments += "--prerelease"
    }
    Invoke-Tool gh $releaseArguments

    Write-Host "Published $tag from $commit."
}
finally {
    Pop-Location
}