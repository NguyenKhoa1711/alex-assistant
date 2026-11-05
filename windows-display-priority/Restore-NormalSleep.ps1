# Close Alex normally before running; reopen it afterwards to read the disabled flag.
$ErrorActionPreference = 'Stop'
$base = 'D:\HỌC TẬP\dự án trợ lý ảo\trợ lý ảo-local'
$package = Join-Path $base 'outputs\Remote-Wait'
if (Get-ScheduledTask -TaskName 'Alex Display Priority' -ErrorAction SilentlyContinue) {
    & (Join-Path $package 'Uninstall-DisplayPriority.ps1')
}
$fastBackupPath = Join-Path $package 'fast-lock-before.json'
$fastBackup = $null
if (Test-Path -LiteralPath $fastBackupPath) {
    if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw 'Run this restore script as Administrator to restore the Antigravity display override.'
    }
    $fastBackup = Get-Content -LiteralPath $fastBackupPath -Raw | ConvertFrom-Json
}
$deployment = Get-Content -LiteralPath (Join-Path $package 'deployment-result.json') -Raw | ConvertFrom-Json
$backup = [IO.Path]::GetFullPath([string]$deployment.Backup)
if (-not $backup.StartsWith(([IO.Path]::GetFullPath($package) + '\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected backup path.' }
$before = Get-Content -LiteralPath (Join-Path $backup 'power-before.json') -Raw | ConvertFrom-Json
$scheme = [guid]::Parse([string]$before.Scheme).ToString()
$sleepSeconds = [uint32]$before.Sleep.AC
if ($null -ne $fastBackup -and ([guid]::Parse([string]$fastBackup.Scheme).ToString() -ne $scheme)) {
    throw 'Display and sleep backups use different power schemes; no settings changed.'
}
foreach ($path in @((Join-Path $base 'outputs\Bionic-pet\config.yaml'),(Join-Path $base 'source\alex-assistant\desktop\config.yaml'))) {
    $text = [IO.File]::ReadAllText($path)
    $text = [regex]::Replace($text, '(?m)^  remote_wait_on_ac: (true|false)\r?$', '  remote_wait_on_ac: false')
    [IO.File]::WriteAllText($path, $text, [Text.UTF8Encoding]::new($false))
}
& powercfg.exe /setacvalueindex $scheme SUB_SLEEP STANDBYIDLE $sleepSeconds
if ($LASTEXITCODE -ne 0) { throw 'Cannot restore AC sleep timeout.' }
if ($null -ne $fastBackup) {
    & powercfg.exe /setacvalueindex $scheme SUB_VIDEO VIDEOCONLOCK ([uint32]$fastBackup.LockDisplayAcSeconds)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot restore lock display timeout.' }
    $overrides = (& powercfg.exe /requestsoverride) -join "`n"
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read display overrides.' }
    if ($fastBackup.OriginalAntigravityOverrideAbsent -and $overrides -match '(?im)^Antigravity\.exe\s+DISPLAY\s*$') {
        & powercfg.exe /requestsoverride PROCESS Antigravity.exe
        if ($LASTEXITCODE -ne 0) { throw 'Cannot restore Antigravity display policy.' }
    } elseif ($overrides -match '(?i)Antigravity\.exe') {
        Write-Warning 'Antigravity overrides changed since installation; preserved for manual review.'
    }
}
$active = (& powercfg.exe /getactivescheme) -join "`n"
if ($active -match [regex]::Escape($scheme)) {
    & powercfg.exe /setactive $scheme
    if ($LASTEXITCODE -ne 0) { throw 'Cannot apply restored sleep timeout.' }
}
Write-Output 'Restored AC sleep/display timeouts and disabled remote wait. Reopen Alex after closing the old instance.'
