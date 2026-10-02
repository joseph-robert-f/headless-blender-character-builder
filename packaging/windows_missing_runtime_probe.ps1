param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$ExpectedHash,
    [Parameter(Mandatory=$true)][string]$ExpectedCommit,
    [Parameter(Mandatory=$true)][string]$ExpectedTree,
    [Parameter(Mandatory=$true)][string]$Output
)
# SPDX-License-Identifier: GPL-3.0-or-later
# Built-in Windows PowerShell/.NET only. No runtime, download, or host changes.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$result = [ordered]@{schema_version=1; successful=$false; checks=@(); scope='Missing-runtime diagnostic only. Application startup remains unavailable.'}
$owned = @()
function Check([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
function Run-Program([string]$Executable, [string]$Arguments, [string]$Directory, [hashtable]$EnvironmentOverrides = @{}) {
    $p = New-Object Diagnostics.Process
    $p.StartInfo = New-Object Diagnostics.ProcessStartInfo
    $p.StartInfo.FileName = $Executable
    $p.StartInfo.Arguments = $Arguments
    $p.StartInfo.WorkingDirectory = $Directory
    $p.StartInfo.UseShellExecute = $false
    $p.StartInfo.CreateNoWindow = $true
    $p.StartInfo.RedirectStandardInput = $true
    $p.StartInfo.RedirectStandardOutput = $true
    $p.StartInfo.RedirectStandardError = $true
    foreach ($key in $EnvironmentOverrides.Keys) {
        $p.StartInfo.EnvironmentVariables[$key] = [string]$EnvironmentOverrides[$key]
    }
    Check ($p.Start()) 'Could not start the requested process.'
    $script:owned += $p
    $stdout = $p.StandardOutput.ReadToEndAsync()
    $stderr = $p.StandardError.ReadToEndAsync()
    $p.StandardInput.Close()
    if (-not $p.WaitForExit(20000)) { $p.Kill(); throw 'Process exceeded 20 seconds.' }
    $p.WaitForExit()
    return [ordered]@{exit_code=$p.ExitCode; stdout=$stdout.Result; stderr=$stderr.Result}
}
try {
    $before = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant()
    Check ($before -ceq $ExpectedHash) 'Archive hash differs from the exact build input.'
    $result.archive_sha256 = $before
    $system = [Environment]::SystemDirectory
    $result.system_directory = $system
    $result.os = [Environment]::OSVersion.Version.ToString()
    $result.runtime_files = @('VCRUNTIME140.dll','VCRUNTIME140_1.dll') | ForEach-Object {
        $path = Join-Path $system $_
        [ordered]@{name=$_; present=[IO.File]::Exists($path)}
    }
    Check (@($result.runtime_files | Where-Object { $_.present }).Count -eq 0) 'This image does not establish the missing-runtime condition.'
    $base = Join-Path ([IO.Path]::GetTempPath()) ('HBCB prerequisite ' + [char]0x96EA + ' ' + [guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($base) | Out-Null
    $positive = Run-Program (Join-Path $system 'cmd.exe') '/d /c echo HBCB_OS_PROCESS_OK' $base
    Check ($positive.exit_code -eq 0 -and $positive.stdout.Contains('HBCB_OS_PROCESS_OK')) 'OS process positive control failed.'
    $result.checks += 'os_process_positive_control'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    # The host validated the exact same immutable archive paths before mounting it.
    [IO.Compression.ZipFile]::ExtractToDirectory($Package, (Join-Path $base 'extracted'))
    $bundle = Join-Path $base 'extracted\hbcb-review-preview'
    $provenance = Get-Content -LiteralPath (Join-Path $bundle 'provenance.json') -Raw | ConvertFrom-Json
    Check ($provenance.commit -ceq $ExpectedCommit -and $provenance.source_tree -ceq $ExpectedTree) 'Package identity differs.'
    Check ($provenance.target -ceq 'windows-x64') 'Unexpected package target.'
    $exe = Join-Path $bundle 'hbcb-review-preview.exe'
    $result.launcher_sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
    $cwd = Join-Path $base 'poison working directory'
    $fakeRoot = Join-Path $base 'fake Windows'
    foreach ($directory in @($cwd, (Join-Path $base 'poison PATH'), (Join-Path $fakeRoot 'System32'))) {
        [IO.Directory]::CreateDirectory($directory) | Out-Null
        foreach ($dll in @('VCRUNTIME140.dll','VCRUNTIME140_1.dll')) {
            [IO.File]::WriteAllText((Join-Path $directory $dll), 'Not a runtime DLL')
        }
    }
    # Poison only the preview child. The PowerShell harness still needs its
    # genuine OS environment for cryptographic providers and final evidence.
    $poison = @{
        PATH = (Join-Path $base 'poison PATH')
        SystemRoot = $fakeRoot
        WINDIR = $fakeRoot
        PYTHONHOME = (Join-Path $base 'no Python')
        PYTHONPATH = (Join-Path $base 'no modules')
    }
    $result.probe = Run-Program $exe '--verify' $cwd $poison
    Check ($result.probe.exit_code -eq 78) 'Expected the missing-prerequisite exit code 78.'
    Check ($result.probe.stdout.Length -eq 0) 'The payload unexpectedly produced stdout.'
    foreach ($text in @('VCRUNTIME140.dll','VCRUNTIME140_1.dll','System32','Windows error','x64',
                        'https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist')) {
        Check ($result.probe.stderr.Contains($text)) ('Missing actionable diagnostic text: ' + $text)
    }
    $result.checks += 'both_runtime_dlls_absent_and_reported_with_exit78'
    $result.checks += 'fresh_unicode_space_extraction_and_poisoned_environment'
    $result.application_startup = 'not_available_missing_prerequisite'
    Check ((Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant() -ceq $before) 'Input archive changed.'
    $result.checks += 'archive_unchanged'
    $result.successful = $true
} catch { $result.error = $_.Exception.Message; Write-Warning $_.Exception.Message }
finally {
    foreach ($p in $owned) {
        try { if (-not $p.HasExited) { $p.Kill(); $null = $p.WaitForExit(5000) } } catch { }
        $p.Dispose()
    }
    $result | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $Output -Encoding UTF8
}
if (-not $result.successful) { exit 1 }
