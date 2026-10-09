param(
    [ValidateSet('X64', 'Arm64')]
    [string] $Architecture = [System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString()
)

$ErrorActionPreference = 'Stop'
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
$installation = & $vswhere -latest -version '[17.0,18.0)' -products '*' -property installationPath
if ($LASTEXITCODE -ne 0 -or !$installation) { throw 'Visual Studio 2022 is required' }
if ($Architecture -eq 'Arm64') {
    $toolsetVersion = '14.44.35207'
    $component = 'Microsoft.VisualStudio.Component.VC.14.44.17.14.ARM64'
    $vcvarsArchitecture = 'arm64'
} else {
    $toolsetVersion = '14.37.32822'
    $component = 'Microsoft.VisualStudio.Component.VC.14.37.17.7.x86.x64'
    $vcvarsArchitecture = 'x64'
}
$toolset = Join-Path $installation "VC/Tools/MSVC/$toolsetVersion"
if (!(Test-Path -LiteralPath "$toolset/lib/$Architecture")) {
    if (!$env:GITHUB_ENV) {
        throw "Install $component with Visual Studio Installer (toolset $toolsetVersion)"
    }
    $installer = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/setup.exe'
    # Component ID from Microsoft's VS 2022 Build Tools component catalog.
    $installArguments = @('modify', '--installPath', ('"{0}"' -f $installation),
        '--add', $component,
        '--quiet', '--norestart')
    $result = Start-Process -FilePath $installer -ArgumentList $installArguments -Wait -PassThru -WindowStyle Hidden
    if ($result.ExitCode -notin @(0, 3010)) { throw "MSVC installation failed: $($result.ExitCode)" }
}
if (!(Test-Path -LiteralPath "$toolset/lib/$Architecture")) {
    throw "Audited MSVC $toolsetVersion for $Architecture was not installed"
}
$vcvars = Join-Path $installation 'VC/Auxiliary/Build/vcvarsall.bat'
$compilerEnvironment = & cmd.exe /s /c ('"{0}" {1} -vcvars_ver={2} >nul && set' -f $vcvars, $vcvarsArchitecture, $toolsetVersion)
if ($LASTEXITCODE -ne 0) { throw 'MSVC environment setup failed' }
foreach ($entry in $compilerEnvironment) {
    if ($entry -match '^([^=]+)=(.*)$') {
        if ([Environment]::GetEnvironmentVariable($matches[1], 'Process') -ne $matches[2]) {
            [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
            if ($env:GITHUB_ENV) {
                $entry | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
            }
        }
    }
}
& cl.exe /Bv /? 2>&1 | Select-Object -First 8 | ForEach-Object { Write-Host $_ }
# bindgen needs libclang; C++ compilation still uses the selected MSVC toolset.
$clangDirectories = if ($Architecture -eq 'Arm64') {
    @(Join-Path $installation 'VC/Tools/Llvm/ARM64/bin')
} else {
    @('C:/Program Files/LLVM/bin', (Join-Path $installation 'VC/Tools/Llvm/x64/bin'))
}
foreach ($directory in $clangDirectories) {
    if (Test-Path -LiteralPath "$directory/libclang.dll") {
        $env:LIBCLANG_PATH = $directory
        if ($env:GITHUB_ENV) {
            "LIBCLANG_PATH=$directory" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
        }
        break
    }
}
