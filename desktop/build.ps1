$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot
$output = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Force $output | Out-Null
Push-Location $repo
try {
    uv sync --locked
    if ($LASTEXITCODE) { throw 'uv sync failed' }
    & .\.venv\Scripts\python.exe third_party/editing/install.py
    if ($LASTEXITCODE) { throw 'Editing skills installation failed' }
    pnpm --dir frontend install --frozen-lockfile
    if ($LASTEXITCODE) { throw 'pnpm install failed' }
    pnpm --dir frontend build
    if ($LASTEXITCODE) { throw 'Frontend build failed' }
} finally {
    Pop-Location
}
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$exe = Join-Path $output '剧灵.exe'
$source = Join-Path $PSScriptRoot 'Launcher.cs'
$icon = Join-Path $repo 'frontend/public/favicon.ico'
& $compiler /nologo /target:winexe /platform:x64 /codepage:65001 "/out:$exe" "/win32icon:$icon" /r:System.Windows.Forms.dll $source
if ($LASTEXITCODE) { throw 'Desktop launcher compilation failed' }
$shell = New-Object -ComObject WScript.Shell
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcut = $shell.CreateShortcut((Join-Path $desktopPath '剧灵.lnk'))
$shortcut.TargetPath = $exe
$shortcut.WorkingDirectory = $repo
$shortcut.Save()
$oldExe = Join-Path $output (([char[]](65,114,99,82,101,101,108) -join '') + '.exe')
$oldShortcut = Join-Path $desktopPath (([char[]](65,114,99,82,101,101,108) -join '') + '.lnk')
if ((Test-Path -LiteralPath $oldShortcut -PathType Leaf) -and $shell.CreateShortcut($oldShortcut).TargetPath -eq $oldExe) {
    Remove-Item -LiteralPath $oldShortcut
}
if (Test-Path -LiteralPath $oldExe -PathType Leaf) { Remove-Item -LiteralPath $oldExe }
Write-Host "Desktop app: $exe"
