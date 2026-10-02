param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$ProjectArchive,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$ExpectedCommit,
    [switch]$RunContainer
)

# Do not pull images, install software, start services, or change OS features.
# The official image must already be present on the GitHub Windows runner.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$image = 'mcr.microsoft.com/windows/servercore:ltsc2022'
$Output = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($Output) | Out-Null
$report = [ordered]@{
    schema_version=1; status='blocked'; image=$image; scope='Windows Server Core process container, not a consumer desktop'
    container_used=$false; supplemental_terms='https://learn.microsoft.com/en-us/virtualization/windowscontainers/images-eula'
    host_changes=@(); package_sha256=(Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant()
}
$name = 'hbcb-install-' + [guid]::NewGuid().ToString('N')
$created = $false
try {
    $hostOs = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $report.host = [ordered]@{product=$hostOs.ProductName; build=$hostOs.CurrentBuildNumber; revision=$hostOs.UBR;
        runner_image=$env:ImageOS; runner_image_version=$env:ImageVersion; architecture=$env:PROCESSOR_ARCHITECTURE}
    $docker = (Get-Command docker -ErrorAction Stop).Source
    $report.docker_version = (& $docker version --format '{{json .}}' 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'The existing Docker service is not available. No service change was made.' }
    $report.docker_info = (& $docker info --format '{{json .}}' 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Docker capability inventory failed.' }
    $info = $report.docker_info | ConvertFrom-Json
    if ($info.OSType -ne 'windows') { throw 'The existing Docker engine does not use Windows containers.' }
    $report.cached_images = (& $docker image ls --digests --no-trunc --format '{{json .}}' 2>&1 | Out-String)
    $inspection = (& $docker image inspect $image 2>&1 | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'The official Server Core image is not cached. No image was pulled.' }
    $parsed = @($inspection | ConvertFrom-Json)[0]
    $report.image_inspect = $parsed
    if ($parsed.Os -ne 'windows' -or $parsed.Architecture -ne 'amd64') { throw 'The cached image has an unexpected OS or architecture.' }
    if (-not (@($parsed.RepoDigests) | Where-Object { $_ -like 'mcr.microsoft.com/windows/servercore@sha256:*' })) {
        throw 'The cached image does not have an official Microsoft repository digest.'
    }
    $hostBuild = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').CurrentBuildNumber
    if ($parsed.OsVersion.Split('.')[2] -ne $hostBuild) { throw 'Container and host build numbers differ. No isolation change was made.' }
    if (-not $RunContainer) { $report.status='inventory_only'; return }
    $inputDirectory = Join-Path $Output 'input'
    [IO.Directory]::CreateDirectory($inputDirectory) | Out-Null
    Copy-Item -LiteralPath $Package -Destination (Join-Path $inputDirectory 'preview.zip')
    Copy-Item -LiteralPath $ProjectArchive -Destination (Join-Path $inputDirectory 'lamp.zip')
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'test-review-preview-install-windows.ps1') -Destination (Join-Path $inputDirectory 'test.ps1')
    $results = Join-Path $Output 'container-results'
    [IO.Directory]::CreateDirectory($results) | Out-Null
    # No host tool directory is mounted. The only network is container loopback.
    $createArgs = @('create','--name',$name,'--isolation=process','--network=none','--pull=never',
        '--mount',('type=bind,source=' + $inputDirectory + ',target=C:\input,readonly'),
        '--mount',('type=bind,source=' + $results + ',target=C:\results'),
        $parsed.Id,'powershell.exe','-NoLogo','-NoProfile','-NonInteractive','-File','C:\input\test.ps1',
        '-Package','C:\input\preview.zip','-ProjectArchive','C:\input\lamp.zip','-Output','C:\results',
        '-ExpectedCommit',$ExpectedCommit,'-EnvironmentKind','servercore-process-container')
    $createdId = (& $docker @createArgs 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw ('Container creation failed. No fallback was attempted. ' + $createdId) }
    $created = $true
    $report.container_used = $true
    $report.container_id = $createdId
    $report.container_inspect = (& $docker inspect $name | ConvertFrom-Json)
    $attached = New-Object Diagnostics.Process
    $attached.StartInfo = New-Object Diagnostics.ProcessStartInfo
    $attached.StartInfo.FileName = $docker
    $attached.StartInfo.Arguments = 'start --attach ' + $name
    $attached.StartInfo.UseShellExecute = $false
    $attached.StartInfo.RedirectStandardOutput = $true
    $attached.StartInfo.RedirectStandardError = $true
    if (-not $attached.Start()) { throw 'The Docker attach process did not start.' }
    $stdout = $attached.StandardOutput.ReadToEndAsync()
    $stderr = $attached.StandardError.ReadToEndAsync()
    $report.container_timed_out = -not $attached.WaitForExit(240000)
    if ($report.container_timed_out) { $attached.Kill() }
    $attached.WaitForExit()
    $report.console = $stdout.Result + $stderr.Result
    $report.docker_start_exit_code = $attached.ExitCode
    $attached.Dispose()
    $state = @(& $docker inspect $name | ConvertFrom-Json)[0]
    $report.final_container_state = $state.State
    $testResult = Join-Path $results 'install-results.json'
    if ($report.container_timed_out) { throw 'The container exceeded 240 seconds. Its owned container will be removed.' }
    if (Test-Path -LiteralPath $testResult) {
        $report.install_result = Get-Content -LiteralPath $testResult -Raw | ConvertFrom-Json
        $report.status = if ($report.install_result.status -eq 'blocked') { 'blocked' }
            elseif ($report.install_result.successful -and $state.State.ExitCode -eq 0) { 'passed' } else { 'failed' }
    } else { throw 'The container did not produce an install report.' }
} catch {
    $report.error = $_.Exception.Message
    Write-Warning $_.Exception.Message
} finally {
    if ($created) {
        # Remove only this test-owned container. Do not remove the base image.
        $report.cleanup = (& $docker rm --force $name 2>&1 | Out-String)
    }
    $report | ConvertTo-Json -Depth 64 | Set-Content -LiteralPath (Join-Path $Output 'servercore-results.json') -Encoding UTF8
}
if ($report.status -eq 'failed') { exit 1 }
if ($report.status -eq 'blocked') { exit 3 }
