param(
    [Parameter(Mandatory=$true)][string]$Package,
    [Parameter(Mandatory=$true)][string]$ProjectArchive,
    [Parameter(Mandatory=$true)][string]$Output,
    [Parameter(Mandatory=$true)][string]$ExpectedCommit,
    [ValidateSet('hosted-runner','servercore-process-container')][string]$EnvironmentKind = 'hosted-runner'
)

# Use built-in Windows PowerShell and .NET only. Do not install a runtime.
# Run this script in a new process. Changes to its environment are temporary.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2
$Output = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($Output) | Out-Null
$result = [ordered]@{
    schema_version = 1; successful = $false; status = 'blocked'; phase = 'inventory'; environment_kind = $EnvironmentKind
    scope = 'Extracted read-only preview. No generation, browser, or consumer desktop trust test.'
    checks = @(); loaded_modules = @(); errors = @()
    package_sha256 = (Get-FileHash -LiteralPath $Package -Algorithm SHA256).Hash.ToLowerInvariant()
    project_archive_sha256 = (Get-FileHash -LiteralPath $ProjectArchive -Algorithm SHA256).Hash.ToLowerInvariant()
}
$owned = @()
$bundle = $null
$project = $null
$beforeBundle = $null
$beforeProject = $null
function Check([bool]$Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
}
function Pass([string]$Name) {
    $result.checks += [ordered]@{name=$Name; status='pass'}
    Write-Host ('PASS ' + $Name)
}
function Hash-Tree([string]$Root) {
    $rows = @()
    foreach ($item in (Get-ChildItem -LiteralPath $Root -Recurse -Force | Sort-Object FullName)) {
        Check (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0) 'Unexpected file link.'
        $path = $item.FullName.Substring($Root.Length).Replace('\','/')
        if ($item.PSIsContainer) { $rows += $path + '/'; continue }
        $rows += $path + ' ' + (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
    }
    return ($rows -join "`n")
}
function Extract-Zip([string]$Archive, [string]$Destination, [string]$RequiredRoot) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead([IO.Path]::GetFullPath($Archive))
    try {
        $total = 0L
        $seen = @{}
        foreach ($entry in $zip.Entries) {
            $name = $entry.FullName
            Check ($name -eq "$RequiredRoot/" -or $name.StartsWith("$RequiredRoot/")) 'Unexpected ZIP root.'
            Check (-not ($name.Contains('\') -or $name.Contains(':') -or $name.StartsWith('/'))) 'Unsafe ZIP path.'
            Check (-not ($name.Split('/') -contains '..')) 'ZIP path traversal.'
            Check (-not $seen.ContainsKey($name)) 'Duplicate ZIP entry.'
            $seen[$name] = $true
            $total += $entry.Length
            Check ($total -lt 1GB -and $seen.Count -lt 4096) 'ZIP exceeds test limit.'
            $kind = (($entry.ExternalAttributes -shr 16) -band 0xF000)
            Check ($kind -ne 0xA000) 'ZIP links are not permitted.'
        }
    } finally { $zip.Dispose() }
    Check (-not (Test-Path -LiteralPath $Destination)) 'Extraction directory already exists.'
    [IO.Compression.ZipFile]::ExtractToDirectory([IO.Path]::GetFullPath($Archive), $Destination)
    return (Join-Path $Destination $RequiredRoot)
}
function Start-Program([string]$Executable, [string]$Arguments, [string]$WorkingDirectory) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $Executable
    $info.Arguments = $Arguments
    $info.WorkingDirectory = $WorkingDirectory
    $info.UseShellExecute = $false
    $info.CreateNoWindow = $true
    $info.RedirectStandardInput = $true
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    $process = New-Object Diagnostics.Process
    $process.StartInfo = $info
    Check ($process.Start()) 'Process did not start.'
    $script:owned += $process
    return $process
}
function Run-Program([string]$Executable, [string]$Arguments, [string]$WorkingDirectory) {
    $p = Start-Program $Executable $Arguments $WorkingDirectory
    $stdout = $p.StandardOutput.ReadToEndAsync()
    $stderr = $p.StandardError.ReadToEndAsync()
    if (-not $p.WaitForExit(30000)) { $p.Kill(); throw 'Process did not stop in 30 seconds.' }
    $p.WaitForExit()
    return [ordered]@{exit_code=$p.ExitCode; stdout=$stdout.Result; stderr=$stderr.Result}
}
function Read-Http([string]$Url, [string]$Type) {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20
    Check ($response.StatusCode -eq 200) ('HTTP read failed: ' + $Url)
    Check ([string]$response.Headers['Content-Type'] -like "$Type*") ('Unexpected HTTP type: ' + $Url)
    Check ($response.RawContentLength -gt 0) ('Empty HTTP result: ' + $Url)
    return $response
}

try {
    $os = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'
    $result.os = [ordered]@{product=$os.ProductName; build=$os.CurrentBuildNumber; revision=$os.UBR;
        version=[Environment]::OSVersion.Version.ToString(); architecture=$env:PROCESSOR_ARCHITECTURE;
        runner_image=$env:ImageOS; runner_image_version=$env:ImageVersion;
        powershell=$PSVersionTable.PSVersion.ToString(); dotnet=[Environment]::Version.ToString()}
    $result.initial_path = $env:PATH
    $result.external_commands = @('python','python3','py','node','npm','blender','docker') | ForEach-Object {
        $name = $_
        [ordered]@{name=$name; paths=@(Get-Command $name -All -ErrorAction SilentlyContinue | ForEach-Object { $_.Source })}
    }
    $result.installed_software = @(
        Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
        Where-Object { $_.PSObject.Properties['DisplayName'] } |
        Select-Object DisplayName, DisplayVersion, Publisher
    )
    $result.system_runtime = @('vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll','ucrtbase.dll') | ForEach-Object {
        $path = Join-Path $env:SystemRoot ('System32\' + $_)
        $row = [ordered]@{path=$path; present=(Test-Path -LiteralPath $path)}
        if ($row.present) {
            $row.version = (Get-Item -LiteralPath $path).VersionInfo.FileVersion
            $row.sha256 = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        }
        $row
    }
    $base = Join-Path ([IO.Path]::GetTempPath()) ('HBCB install test ' + [guid]::NewGuid().ToString('N'))
    [IO.Directory]::CreateDirectory($base) | Out-Null
    $result.test_directory = $base
    $result.phase = 'extraction'
    $bundle = Extract-Zip $Package (Join-Path $base ('Fresh extraction ' + [char]0x96EA)) 'hbcb-review-preview'
    $project = Extract-Zip $ProjectArchive (Join-Path $base ('Lamp project ' + [char]0x96E8)) 'desk-lamp-demo'
    $cwd = Join-Path $base 'Empty working directory'
    [IO.Directory]::CreateDirectory($cwd) | Out-Null
    $exe = Join-Path $bundle 'hbcb-review-preview.exe'
    $result.signature = Get-AuthenticodeSignature -LiteralPath $exe | Select-Object Status, StatusMessage, SignerCertificate
    $result.provenance_from_file = Get-Content -LiteralPath (Join-Path $bundle 'provenance.json') -Raw | ConvertFrom-Json
    Check ($result.provenance_from_file.commit -eq $ExpectedCommit) 'Package source commit differs from expected commit.'
    Check ($result.provenance_from_file.target -eq 'windows-x64') 'Package target is not Windows x64.'
    $readme = Get-Content -LiteralPath (Join-Path $bundle 'README.md') -Raw
    foreach ($instruction in @('Expand-Archive', '.\hbcb-review-preview.exe --verify', '.\hbcb-review-preview.exe --project', 'type `q`')) {
        Check ($readme.Contains($instruction)) ('Packaged README instruction differs: ' + $instruction)
    }
    $beforeProject = Hash-Tree $project
    $beforeBundle = Hash-Tree $bundle
    Pass 'fresh_archive_extraction_with_spaces_and_unicode'

    # The native harness uses full paths. These changes cannot remove System32 DLLs.
    $env:PATH = ''
    $env:PYTHONHOME = Join-Path $base 'no-external-python'
    $env:PYTHONPATH = Join-Path $base 'no-source-imports'
    $env:PYTHONUTF8 = '1'
    $result.phase = 'os_positive_control'
    $positive = Run-Program (Join-Path $env:SystemRoot 'System32\cmd.exe') '/d /c echo HBCB_OS_PROCESS_OK' $cwd
    Check ($positive.exit_code -eq 0 -and $positive.stdout.Contains('HBCB_OS_PROCESS_OK')) 'OS process positive control failed.'
    Pass 'os_process_positive_control'
    $result.phase = 'preview_checks'
    $result.verify = Run-Program $exe '--verify' $bundle
    Check ($result.verify.exit_code -eq 0) ('README --verify failed: ' + $result.verify.stderr)
    $verified = $result.verify.stdout | ConvertFrom-Json
    Check ($verified.verified -eq $true) 'Package verification did not pass.'
    Pass 'readme_verify_from_extracted_folder'
    $result.provenance_command = Run-Program $exe '--provenance' $cwd
    Check ($result.provenance_command.exit_code -eq 0) 'Provenance command failed.'
    foreach ($case in @(
        @{name='no_arguments'; args=''},
        @{name='missing_project_argument'; args='--project'},
        @{name='absent_project_directory'; args=('--project "' + (Join-Path $base 'missing-project') + '"')},
        @{name='generation_is_unavailable'; args=('--project "' + $project + '" --generate')}
    )) {
        $row = Run-Program $exe $case.args $bundle
        $result[$case.name] = $row
        Check ($row.exit_code -eq 2 -and ($row.stderr + $row.stdout).Length -gt 0) ('Expected usage error: ' + $case.name)
        if ($case.name -eq 'generation_is_unavailable') {
            Check ($row.stderr.Contains('unrecognized arguments: --generate')) 'The unsupported generation option was not identified.'
        }
        Pass $case.name
    }

    # Negative control: use another copy and omit its Python DLL. Keep the tested bundle intact.
    $damaged = Join-Path $base 'Missing bundled Python control'
    Copy-Item -LiteralPath $bundle -Destination $damaged -Recurse
    Check ($result.provenance_from_file.python -match '^(\d+)\.(\d+)\.') 'The Python version cannot identify its runtime DLL.'
    $runtimeName = 'python' + $Matches[1] + $Matches[2] + '.dll'
    $pythonDll = @(Get-ChildItem -LiteralPath $damaged -Filter $runtimeName -Recurse -File)
    Check ($pythonDll.Count -eq 1) 'The negative control must identify exactly one main Python runtime DLL.'
    Rename-Item -LiteralPath $pythonDll[0].FullName -NewName ($pythonDll[0].Name + '.test-disabled')
    $result.missing_bundled_python_control = Run-Program (Join-Path $damaged 'hbcb-review-preview.exe') '--verify' $cwd
    Check ($result.missing_bundled_python_control.exit_code -ne 0) 'Missing Python DLL was not detected.'
    Pass 'missing_bundled_python_negative_control'

    $server = Start-Program $exe ('--project "' + $project + '" --port 0') $bundle
    $stderr = $server.StandardError.ReadToEndAsync()
    $lines = @()
    $origin = $null
    $deadline = [DateTime]::UtcNow.AddSeconds(30)
    for ($i=0; $i -lt 16 -and [DateTime]::UtcNow -lt $deadline; $i++) {
        $line = $server.StandardOutput.ReadLineAsync()
        $remaining = [int][Math]::Max(1, ($deadline - [DateTime]::UtcNow).TotalMilliseconds)
        Check ($line.Wait($remaining)) 'The preview did not show an address in 30 seconds.'
        if ($null -eq $line.Result) { break }
        $lines += $line.Result
        if ($line.Result -match '^Local project review: (http://127\.0\.0\.1:[0-9]+)$') { $origin=$Matches[1]; break }
    }
    $result.startup_lines = $lines
    Check ($null -ne $origin) 'The preview did not start the local server.'
    $server.Refresh()
    $result.loaded_modules = @($server.Modules | ForEach-Object {
        [ordered]@{path=$_.FileName; name=$_.ModuleName; version=$_.FileVersionInfo.FileVersion;
            sha256=(Get-FileHash -LiteralPath $_.FileName -Algorithm SHA256).Hash.ToLowerInvariant()}
    })
    $result.external_non_os_modules = @($result.loaded_modules | Where-Object {
        -not $_.path.StartsWith($bundle + '\', [StringComparison]::OrdinalIgnoreCase) -and
        -not $_.path.StartsWith($env:SystemRoot + '\', [StringComparison]::OrdinalIgnoreCase)
    })
    $data = (Read-Http ($origin + '/api/project') 'application/json').Content | ConvertFrom-Json
    Check ($data.read_only -eq $true) 'The backend is not read-only.'
    Check ($data.latest_revision -eq 'lamp-slim-repair') 'The final lamp revision is not selected.'
    Check (@($data.revisions).Count -eq 4) 'The lamp project must contain four revisions.'
    $null = Read-Http ($origin + '/') 'text/html'
    $null = Read-Http ($origin + '/static/app.js') 'text/javascript'
    $null = Read-Http ($origin + '/static/style.css') 'text/css'
    $result.lamp_revisions = @()
    foreach ($id in @('lamp-r0','lamp-r1','lamp-slim-bad','lamp-slim-repair')) {
        $revision = (Read-Http ($origin + '/api/revisions/' + $id) 'application/json').Content | ConvertFrom-Json
        $expectedVerified = $id -ne 'lamp-slim-bad'
        Check ($revision.report.machine_verified -eq $expectedVerified) ('Lamp verification differs: ' + $id)
        Check ($revision.state.human_accepted -eq $false) ('Unexpected human acceptance: ' + $id)
        Check (@($revision.artifacts.views).Count -eq 4) ('Missing saved lamp views: ' + $id)
        foreach ($view in $revision.artifacts.views) { $null = Read-Http ($origin + $view.url) 'image/png' }
        $null = Read-Http ($origin + $revision.artifacts.glb_url) 'model/gltf-binary'
        $result.lamp_revisions += [ordered]@{id=$id; machine_verified=$revision.report.machine_verified; human_accepted=$false; result_hash=$revision.revision.result_hash}
    }
    Pass 'real_portable_lamp_http_static_image_and_model_reads'
    $payload = @{csrf_token=$data.csrf_token; expected_result_hash=$revision.revision.result_hash;
        revision_id='lamp-slim-repair'; notes='Install test must not write'; prompt='Install test must not write'} | ConvertTo-Json
    foreach ($endpoint in @('/api/revisions/lamp-slim-repair/accept', '/api/requests')) {
        $status = 0
        try {
            $response = Invoke-WebRequest -Uri ($origin + $endpoint) -Method Post -UseBasicParsing -TimeoutSec 20 `
                -ContentType 'application/json' -Body $payload -Headers @{Origin=$origin}
            $status = [int]$response.StatusCode
        } catch {
            if ($null -eq $_.Exception.Response) { throw }
            $status = [int]$_.Exception.Response.StatusCode
        }
        Check ($status -eq 403) ('Read-only write was not blocked: ' + $endpoint)
    }
    Pass 'backend_write_requests_denied'
    $server.StandardInput.WriteLine('q')
    $server.StandardInput.Flush()
    Check ($server.WaitForExit(20000)) 'The preview did not stop after q.'
    $server.WaitForExit()
    Check ($server.ExitCode -eq 0) 'Controlled shutdown failed.'
    $result.shutdown = [ordered]@{exit_code=$server.ExitCode; stdout=$server.StandardOutput.ReadToEnd(); stderr=$stderr.Result}
    Pass 'controlled_shutdown'
    Check ((Hash-Tree $project) -ceq $beforeProject) 'Project contents changed.'
    Check ((Hash-Tree $bundle) -ceq $beforeBundle) 'Package contents changed.'
    Pass 'project_and_bundle_content_unchanged'
    $result.successful = $true
    $result.status = 'passed'
} catch {
    $result.status = 'failed'
    $exception = $_.Exception
    while ($null -ne $exception.InnerException) { $exception = $exception.InnerException }
    if ($result.phase -in @('inventory','os_positive_control') -or
        $exception -is [System.Management.Automation.CommandNotFoundException] -or
        ($exception -is [System.ComponentModel.Win32Exception] -and $exception.NativeErrorCode -in @(5,577,740,1260))) {
        $result.status = 'blocked'
    }
    $result.exception_type = $exception.GetType().FullName
    $result.errors += $_.Exception.Message
    Write-Warning $_.Exception.Message
} finally {
    foreach ($process in $owned) {
        try { if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit(10000) | Out-Null } } catch { }
        $process.Dispose()
    }
    if ($null -ne $beforeProject -and $null -ne $beforeBundle) {
        try {
            $result.project_content_unchanged = (Hash-Tree $project) -ceq $beforeProject
            $result.package_content_unchanged = (Hash-Tree $bundle) -ceq $beforeBundle
            if (-not ($result.project_content_unchanged -and $result.package_content_unchanged)) {
                $result.successful = $false
                $result.status = 'failed'
                $result.errors += 'Project or package contents changed.'
            }
        } catch { $result.successful=$false; $result.status='failed'; $result.errors += ('Final content check failed: ' + $_.Exception.Message) }
    }
    $result | ConvertTo-Json -Depth 32 | Set-Content -LiteralPath (Join-Path $Output 'install-results.json') -Encoding UTF8
}
if (-not $result.successful) { exit 1 }
