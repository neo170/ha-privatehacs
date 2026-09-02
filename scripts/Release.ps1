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

Push-Location $repoRoot
try {
  $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
  $currentVersion = [Version]$manifest.version
  $newVersion = "{0}.{1}.{2}" -f $currentVersion.Major, $currentVersion.Minor, ($currentVersion.Build + 1)

  $manifestContent = Get-Content -LiteralPath $manifestPath -Raw
  $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
  $updatedManifestContent = [regex]::Replace(
    $manifestContent,
    '"version"\s*:\s*"[^"]+"',
    '"version": "' + $newVersion + '"',
    1
  )
  [System.IO.File]::WriteAllText($manifestPath, $updatedManifestContent, $utf8WithoutBom)

  $projectContent = Get-Content -LiteralPath $projectPath -Raw
  $updatedProjectContent = [regex]::Replace(
    $projectContent,
    '(?m)^version = "[^"]+"\s*$',
    'version = "' + $newVersion + '"',
    1
  )
  [System.IO.File]::WriteAllText($projectPath, $updatedProjectContent, $utf8WithoutBom)

  Invoke-GitHubCommand "git" (@("add", "-A", "--") + $releasePaths)
  $tag = "v$newVersion"
  Invoke-GitHubCommand "git" @("commit", "-m", "${tag}: $Description")
  Invoke-GitHubCommand "git" @("tag", "-a", $tag, "-m", $tag)
  Invoke-GitHubCommand "git" @("push", "origin", "main")
  Invoke-GitHubCommand "git" @("push", "origin", $tag)
  Invoke-GitHubCommand "gh" @("release", "create", $tag, "--repo", "neo170/ha-privatehacs", "--title", $tag, "--notes", $Description, "--verify-tag")

  Write-Host "Release $tag was published successfully."
} finally {
  Pop-Location
}