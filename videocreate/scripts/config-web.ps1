[CmdletBinding()]
param(
    [string]$Python = "python",
    [string]$Config,
    [int]$Port = 8787,
    [switch]$ReadOnly,
    [switch]$NoBrowser
)
$ErrorActionPreference = "Stop"
$entry = Join-Path $PSScriptRoot "videocreate.py"
if (-not (Test-Path -LiteralPath $entry -PathType Leaf)) { throw "VideoCreate CLI is missing." }
# The shared CLI classifies missing packages and runtime/DLL load failures.
# Do not run a separate import probe that prints a traceback or mislabels both.
$webArguments = @($entry, "config-web", "--port", [string]$Port)
if ($Config) { $webArguments += @("--config", $Config) }
if ($ReadOnly) { $webArguments += "--read-only" }
if ($NoBrowser) { $webArguments += "--no-browser" }
Write-Host "VideoCreate configuration Web. Close this terminal or press Ctrl+C to stop this configuration instance. Media hosting remains independent."
& $Python @webArguments
exit $LASTEXITCODE
