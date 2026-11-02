[CmdletBinding()]
param(
    [string]$Destination,
    [string]$Python = "python",
    [switch]$Force,
    [switch]$Repair,
    [switch]$Check,
    [switch]$Uninstall,
    [switch]$Configure,
    [switch]$ConfigureFromStdin,
    [switch]$SkipProviderTest,
    [ValidateSet("basic", "upstream-dialogue", "precise-subtitles", "precise-voice", "lip-sync")]
    [string]$InstallProfile = "upstream-dialogue",
    [switch]$Interactive,
    [ValidateSet("core", "native-dialogue", "local-voice", "full-dialogue")]
    [string]$ComponentProfile = "core",
    [string]$ComponentSourceRoot,
    [string]$ComponentModelsRoot,
    [switch]$InstallComponents,
    [switch]$IncludeComponentModels,
    [switch]$AcceptComponentDownloads,
    [switch]$InstallSystemDependencies,
    [switch]$AcceptSystemDependencyChanges,
    [switch]$StartComponents,
    [ValidateSet("cosyvoice", "musetalk", "all")]
    [string]$StartComponent
)

$ErrorActionPreference = "Stop"
$operationCount = @($Check, $Uninstall) | Where-Object { $_ } | Measure-Object | Select-Object -ExpandProperty Count
if ($operationCount -gt 1) {
    throw "Use only one of -Check or -Uninstall."
}
if ($Repair) {
    $Force = $true
}
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$source = Join-Path $repoRoot "videocreate"
if (-not (Test-Path -LiteralPath (Join-Path $source "SKILL.md") -PathType Leaf)) {
    throw "Skill source is incomplete: $source"
}

if ([string]::IsNullOrWhiteSpace($Destination)) {
    $codexRoot = if ([string]::IsNullOrWhiteSpace($env:CODEX_HOME)) {
        Join-Path $env:USERPROFILE ".codex"
    } else {
        $env:CODEX_HOME
    }
    $Destination = Join-Path (Join-Path $codexRoot "skills") "videocreate"
}

$sourcePath = [IO.Path]::GetFullPath($source)
$destinationPath = [IO.Path]::GetFullPath($Destination)

if ($Check) {
    if (-not (Test-Path -LiteralPath $destinationPath -PathType Container)) {
        throw "Installed Skill was not found at $destinationPath"
    }
    $installedCli = Join-Path $destinationPath "scripts\videocreate.py"
    & $Python $installedCli version
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Skill did not pass the version check."
    }
    & $Python $installedCli install-plan --profile upstream-dialogue
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Skill install-plan check failed."
    }
    Write-Host "VideoCreate installation is readable at $destinationPath"
    exit 0
}

if ($Uninstall) {
    if (-not (Test-Path -LiteralPath $destinationPath -PathType Container)) {
        Write-Host "VideoCreate is not installed at $destinationPath"
        exit 0
    }
    $resolvedParent = [IO.Path]::GetFullPath((Split-Path -Parent $destinationPath))
    if (-not $destinationPath.StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar) -or
        [IO.Path]::GetFileName($destinationPath) -ne "videocreate") {
        throw "Refusing to remove an unexpected destination: $destinationPath"
    }
    $existingItem = Get-Item -LiteralPath $destinationPath -Force
    if (($existingItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to remove a reparse-point destination: $destinationPath"
    }
    foreach ($item in Get-ChildItem -LiteralPath $destinationPath -Recurse -Force -ErrorAction Stop) {
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw "Refusing to remove an installation that contains a reparse point: $($item.FullName)"
        }
        if (-not $item.PSIsContainer) {
            $stream = $null
            try {
                $stream = [IO.File]::Open(
                    $item.FullName,
                    [IO.FileMode]::Open,
                    [IO.FileAccess]::Read,
                    [IO.FileShare]::None
                )
            }
            catch {
                throw "Cannot uninstall while a Skill file is in use: $($item.FullName)"
            }
            finally {
                if ($null -ne $stream) {
                    $stream.Dispose()
                }
            }
        }
    }
    Remove-Item -LiteralPath $destinationPath -Recurse -Force
    Write-Host "Removed the VideoCreate Skill files from $destinationPath"
    Write-Host "User credentials, projects, component sources, and model weights were preserved."
    exit 0
}

if ($Configure -and $ConfigureFromStdin) {
    throw "Use either -Configure or -ConfigureFromStdin, not both."
}
if ($sourcePath -eq $destinationPath) {
    throw "Source and destination must be different directories."
}

$installProfileExplicit = $PSBoundParameters.ContainsKey("InstallProfile") -or $PSBoundParameters.ContainsKey("ComponentProfile")
$selectedInstallProfile = $InstallProfile
if (-not $Interactive -and -not $installProfileExplicit) {
    $profileConfigRoot = if (-not [string]::IsNullOrWhiteSpace($env:VIDEOCREATE_CONFIG_DIR)) {
        $env:VIDEOCREATE_CONFIG_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Join-Path $env:LOCALAPPDATA "VideoCreate"
    } else {
        Join-Path (Join-Path $env:USERPROFILE ".config") "VideoCreate"
    }
    $savedProfilePath = Join-Path $profileConfigRoot "install-profile.json"
    if (-not (Test-Path -LiteralPath $savedProfilePath) -and [string]::IsNullOrWhiteSpace($env:VIDEOCREATE_CONFIG_DIR)) {
        $legacyProfile = Join-Path (Join-Path $env:LOCALAPPDATA "GrokVideoSkill") "install-profile.json"
        if (Test-Path -LiteralPath $legacyProfile) { $savedProfilePath = $legacyProfile }
    }
    if (Test-Path -LiteralPath $savedProfilePath -PathType Leaf) {
        try {
            $savedProfile = (Get-Content -LiteralPath $savedProfilePath -Raw | ConvertFrom-Json).profile
        }
        catch {
            throw "Existing install profile metadata is invalid: $savedProfilePath"
        }
        if ($savedProfile -notin @("basic", "upstream-dialogue", "precise-subtitles", "precise-voice", "lip-sync")) {
            throw "Existing install profile is unsupported: $savedProfile"
        }
        $selectedInstallProfile = $savedProfile
    }
}
if ($ComponentProfile -ne "core" -and $InstallProfile -eq "basic") {
    $selectedInstallProfile = @{
        "native-dialogue" = "upstream-dialogue"
        "local-voice" = "precise-voice"
        "full-dialogue" = "lip-sync"
    }[$ComponentProfile]
}
if ($Interactive) {
    $profileInput = Read-Host "Choose profile: basic, upstream-dialogue, precise-subtitles, precise-voice, lip-sync (default: $selectedInstallProfile)"
    if (-not [string]::IsNullOrWhiteSpace($profileInput)) {
        $selectedInstallProfile = $profileInput.Trim().ToLowerInvariant()
    }
    if ($selectedInstallProfile -notin @("basic", "upstream-dialogue", "precise-subtitles", "precise-voice", "lip-sync")) {
        throw "Unknown install profile: $selectedInstallProfile"
    }
    $Configure = $true
}
$profileComponentMap = @{
    "basic" = "core"
    "upstream-dialogue" = "native-dialogue"
    "precise-subtitles" = "core"
    "precise-voice" = "local-voice"
    "lip-sync" = "full-dialogue"
}
$selectedComponentProfile = $profileComponentMap[$selectedInstallProfile]
if ([string]::IsNullOrWhiteSpace($selectedComponentProfile)) {
    throw "Install profile mapping is invalid: $selectedInstallProfile"
}
if ($Interactive -and $selectedInstallProfile -in @("precise-voice", "lip-sync")) {
    $componentChoice = Read-Host "Download and build the optional local AI services and pinned models now? (y/N)"
    if ($componentChoice.Trim().ToLowerInvariant() -in @("y", "yes")) {
        $InstallComponents = $true
        $IncludeComponentModels = $true
        $AcceptComponentDownloads = $true
    }
}
if ($Interactive) {
    $needsDocker = $selectedInstallProfile -in @("precise-voice", "lip-sync") -and -not (Get-Command docker -ErrorAction SilentlyContinue)
    $needsFfmpeg = -not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)
    if ($needsDocker -or $needsFfmpeg) {
        $systemChoice = Read-Host "Install missing FFmpeg/Docker system dependencies through winget? (y/N)"
        if ($systemChoice.Trim().ToLowerInvariant() -in @("y", "yes")) {
            $InstallSystemDependencies = $true
            $AcceptSystemDependencyChanges = $true
        }
    }
}
if ($InstallSystemDependencies -and -not $AcceptSystemDependencyChanges) {
    throw "System dependency installation requires -AcceptSystemDependencyChanges after the user approves package-manager changes."
}
if ($Interactive -and $InstallComponents -and $selectedInstallProfile -eq "lip-sync") {
    $startChoice = Read-Host "Start a local service after installation? Use cosyvoice, musetalk, all, or N (default: N)"
    if ($startChoice.Trim().ToLowerInvariant() -in @("cosyvoice", "musetalk", "all")) {
        $StartComponents = $true
        $StartComponent = $startChoice.Trim().ToLowerInvariant()
    }
}
if ($ConfigureFromStdin -and $Interactive) {
    throw "Use either -Interactive or -ConfigureFromStdin, not both."
}

$destinationParent = Split-Path -Parent $destinationPath
New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
 $backupPath = $null
if (Test-Path -LiteralPath $destinationPath) {
    if (-not $Force) {
        throw "Skill already exists at $destinationPath. Re-run with -Force to update it."
    }
    $resolvedParent = [IO.Path]::GetFullPath($destinationParent)
    if (-not $destinationPath.StartsWith($resolvedParent + [IO.Path]::DirectorySeparatorChar) -or
        [IO.Path]::GetFileName($destinationPath) -ne "videocreate") {
        throw "Refusing to replace an unexpected destination: $destinationPath"
    }
    $existingItem = Get-Item -LiteralPath $destinationPath -Force
    if (($existingItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to replace a reparse-point destination: $destinationPath"
    }
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backupRoot = Join-Path (Split-Path -Parent $destinationParent) "skill-backups"
    New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null
    $backupPath = Join-Path $backupRoot "videocreate-$stamp-$([guid]::NewGuid().ToString('N').Substring(0,8))"
    Move-Item -LiteralPath $destinationPath -Destination $backupPath
}

try {
    Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Recurse -Force
    $cli = Join-Path $destinationPath "scripts\videocreate.py"
    & $Python $cli version
    if ($LASTEXITCODE -ne 0) {
        throw "Installed Skill did not pass the version check."
    }

& $Python $cli install-plan --profile $selectedInstallProfile
if ($LASTEXITCODE -ne 0) {
    throw "Install profile plan check failed."
}
if ($InstallSystemDependencies) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is required for approved system dependency installation. Install App Installer or install dependencies manually."
    }
    $systemDependencies = @()
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        $systemDependencies += "ffmpeg"
    }
    if ($selectedInstallProfile -in @("precise-voice", "lip-sync") -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
        $systemDependencies += "docker"
    }
    if ($selectedInstallProfile -in @("precise-voice", "lip-sync") -and -not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        throw "NVIDIA GPU dependency is not installed; install a compatible NVIDIA driver manually before using this profile."
    }
    foreach ($dependency in $systemDependencies) {
        $packageId = if ($dependency -eq "ffmpeg") { "Gyan.FFmpeg" } else { "Docker.DockerDesktop" }
        Write-Host "Installing $dependency through winget package $packageId"
        & winget install --id $packageId --exact --source winget --accept-source-agreements --accept-package-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0) {
            throw "winget failed while installing $packageId."
        }
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        throw "FFmpeg was installed but is not visible in this PowerShell session; restart the shell and run the installer again."
    }
    if ($selectedInstallProfile -in @("precise-voice", "lip-sync") -and -not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker Desktop was installed but is not visible in this PowerShell session; restart the shell and run the installer again."
    }
}
if ($Configure -or $ConfigureFromStdin) {
    $arguments = @($cli, "config", "open")
    if ($ConfigureFromStdin) {
        $arguments = @($cli, "config", "import", "--replace")
    }
    & $Python $cli config init
    & $Python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Skill configuration failed."
    }
}
else {
    $newConfigRoot = if (-not [string]::IsNullOrWhiteSpace($env:VIDEOCREATE_CONFIG_DIR)) {
        $env:VIDEOCREATE_CONFIG_DIR
    } elseif (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        Join-Path $env:LOCALAPPDATA "VideoCreate"
    } else {
        Join-Path (Join-Path $env:USERPROFILE ".config") "VideoCreate"
    }
    $legacyConfigRoot = if (-not [string]::IsNullOrWhiteSpace($env:GVS_CONFIG_DIR)) {
        $env:GVS_CONFIG_DIR
    } else {
        Join-Path $env:LOCALAPPDATA "GrokVideoSkill"
    }
    if (-not (Test-Path -LiteralPath (Join-Path $newConfigRoot "videocreate.config.json")) -and
        [string]::IsNullOrWhiteSpace($env:VIDEOCREATE_CONFIG_DIR) -and
        (Test-Path -LiteralPath (Join-Path $legacyConfigRoot "config.json"))) {
        & $Python $cli config migrate --source $legacyConfigRoot --destination $newConfigRoot --apply
        if ($LASTEXITCODE -ne 0) { throw "Configuration migration failed; original configuration is preserved." }
    } else {
        & $Python $cli config init
        if ($LASTEXITCODE -ne 0) { throw "Configuration initialization failed." }
    }
}

$componentArguments = @($cli, "components-configure", "--profile", $selectedComponentProfile)
if (-not [string]::IsNullOrWhiteSpace($ComponentSourceRoot)) {
    $componentArguments += @("--source-root", $ComponentSourceRoot)
}
if (-not [string]::IsNullOrWhiteSpace($ComponentModelsRoot)) {
    $componentArguments += @("--models-root", $ComponentModelsRoot)
}
& $Python @componentArguments
if ($LASTEXITCODE -ne 0) {
    throw "Component profile configuration failed."
}

if ($InstallComponents) {
    if ($selectedComponentProfile -notin @("local-voice", "full-dialogue")) {
        throw "-InstallComponents requires an install profile with local AI services."
    }
    if (-not $AcceptComponentDownloads) {
        throw "Component installation requires -AcceptComponentDownloads after the user approves downloads."
    }
    & $Python $cli components-install --profile $selectedComponentProfile --accept-downloads
    if ($LASTEXITCODE -ne 0) {
        throw "Optional component source installation failed."
    }
    $setupArguments = @($cli, "components-setup", "--profile", $selectedComponentProfile, "--accept-downloads")
    if ($IncludeComponentModels) {
        $setupArguments += "--include-models"
    }
    & $Python @setupArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Optional component runtime setup failed."
    }
}

& $Python $cli install-configure --profile $selectedInstallProfile
if ($LASTEXITCODE -ne 0) {
    throw "Install profile configuration failed."
}

if ($StartComponents) {
    if (-not $InstallComponents -or -not $IncludeComponentModels) {
        throw "-StartComponents requires -InstallComponents and -IncludeComponentModels."
    }
    if ($selectedComponentProfile -eq "full-dialogue" -and [string]::IsNullOrWhiteSpace($StartComponent)) {
        throw "-StartComponents with full-dialogue requires -StartComponent cosyvoice, musetalk, or all."
    }
    $startArguments = @($cli, "components-start", "--profile", $selectedComponentProfile)
    if (-not [string]::IsNullOrWhiteSpace($StartComponent)) {
        $startArguments += @("--component", $StartComponent)
    }
    & $Python @startArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Optional component services failed to start."
    }
}

Write-Host "Installed VideoCreate to $destinationPath"
Write-Host "Install profile: $selectedInstallProfile"
Write-Host "Component profile: $selectedComponentProfile"
if (-not $Configure -and -not $ConfigureFromStdin) {
    Write-Host "Next: videocreate config open; fill URLs/auth/remote_model and enable bindings, then config validate --ready."
}
if ($backupPath) {
    Write-Host "Previous installation preserved at $backupPath"
}
$legacySkillPath = Join-Path $destinationParent "grok-video-studio"
if ((Test-Path -LiteralPath $legacySkillPath -PathType Container) -and
    [IO.Path]::GetFileName($destinationPath) -eq "videocreate" -and
    [IO.Path]::GetFileName($destinationParent) -eq "skills") {
    $legacyItem = Get-Item -LiteralPath $legacySkillPath -Force
    if (($legacyItem.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Refusing to archive a legacy skill through a reparse point."
    }
    $archiveRoot = Join-Path (Split-Path -Parent $destinationParent) "skill-backups"
    New-Item -ItemType Directory -Path $archiveRoot -Force | Out-Null
    $legacyArchive = Join-Path $archiveRoot ("legacy-v2-" + [guid]::NewGuid().ToString("N"))
    Move-Item -LiteralPath $legacySkillPath -Destination $legacyArchive
    Write-Host "Legacy skill archived outside discovery paths at $legacyArchive"
}
}
catch {
    if (Test-Path -LiteralPath $destinationPath -PathType Container) {
        Remove-Item -LiteralPath $destinationPath -Recurse -Force
    }
    if ($backupPath -and (Test-Path -LiteralPath $backupPath -PathType Container)) {
        Move-Item -LiteralPath $backupPath -Destination $destinationPath
    }
    throw
}
