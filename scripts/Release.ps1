param(
  [Parameter(Mandatory, Position = 0)]
  [string]$Description
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-GitHubCommand {
  param(
    [Parameter(Mandatory)][string]$Command,
    [Parameter(Mandatory)][string[]]$Arguments
  )

  & $Command @Arguments
  if ($LASTEXITCODE -ne 0) {
    throw "'$Command $($Arguments -join ' ')' failed with exit code $LASTEXITCODE."
  }
}

function Set-Utf8FileContent {
  param(
    [Parameter(Mandatory)][string]$Path,
    [Parameter(Mandatory)][string]$Content
  )

  $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Content, $utf8WithoutBom)
}

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$manifestPath = Join-Path $repoRoot "custom_components/privatehacs/manifest.json"
$projectPath = Join-Path $repoRoot "pyproject.toml"
$releasePaths = @(
  "custom_components/privatehacs",
  "pyproject.toml",
  "README.md",
  "hacs.json",
  "tests",
  "scripts/Release.ps1"
)

$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
  throw "Required command was not found: python"
}

Push-Location $repoRoot
try {
  $manifestContent = Get-Content -LiteralPath $manifestPath -Raw
  $manifest = $manifestContent | ConvertFrom-Json
  $projectContent = Get-Content -LiteralPath $projectPath -Raw
  $projectVersionMatch = [regex]::Match($projectContent, '(?m)^version = "(?<version>[^"]+)"\s*$')
  if (-not $projectVersionMatch.Success -or $manifest.version -ne $projectVersionMatch.Groups["version"].Value) {
    throw "manifest.json and pyproject.toml do not have the same version."
  }

  $currentVersion = [Version]$manifest.version
  $newVersion = "{0}.{1}.{2}" -f $currentVersion.Major, $currentVersion.Minor, ($currentVersion.Build + 1)
  $tag = "v$newVersion"

  $updatedManifestContent = [regex]::Replace(
    $manifestContent,
    '"version"\s*:\s*"[^"]+"',
    '"version": "' + $newVersion + '"',
    1
  )
  Set-Utf8FileContent $manifestPath $updatedManifestContent

  $updatedProjectContent = [regex]::Replace(
    $projectContent,
    '(?m)^version = "[^"]+"\s*$',
    'version = "' + $newVersion + '"',
    1
  )
  Set-Utf8FileContent $projectPath $updatedProjectContent

  Invoke-GitHubCommand $pythonCommand.Source @("-m", "pytest")
  Invoke-GitHubCommand "node" @("--check", "custom_components/privatehacs/frontend/privatehacs-panel.js")
  Invoke-GitHubCommand "git" @("diff", "--check")

  Invoke-GitHubCommand "git" (@("add", "-A", "--") + $releasePaths)
  Invoke-GitHubCommand "git" @("commit", "-m", "$tag`: $Description")
  Invoke-GitHubCommand "git" @("tag", "-a", $tag, "-m", "$tag`: $Description")
  Invoke-GitHubCommand "git" @("push", "origin", "main")
  Invoke-GitHubCommand "git" @("push", "origin", $tag)
  Invoke-GitHubCommand "gh" @("release", "create", $tag, "--repo", "neo170/ha-privatehacs", "--title", $tag, "--notes", $Description, "--verify-tag")

  Write-Host "Release $tag was published successfully."
} finally {
  Pop-Location
}