param([Parameter(Mandatory=$true)][string]$ExpectedUserSid)
$ErrorActionPreference='Stop'
trap { $_ | Out-String | Set-Content -LiteralPath 'D:\AlexDisplayPriority-install-error.txt' -Encoding utf8; exit 1 }
Start-Transcript -LiteralPath 'D:\AlexDisplayPriority-install.log' -Append | Out-Null
$root='D:\AlexPowerPriority-System'
$taskName='Alex Display Priority'
$sid=[Security.Principal.WindowsIdentity]::GetCurrent().User.Value
if ($ExpectedUserSid -notmatch '^S-1-5-21-(\d+-){3}\d+$' -or $sid -ne $ExpectedUserSid) { throw 'Unexpected user SID.' }
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator required.' }
$binary=Join-Path $PSScriptRoot 'AlexDisplayPriority.exe'
if ((Get-FileHash -LiteralPath $binary -Algorithm SHA256).Hash -ne '9F72A1A15175B06C120AF616F3222C94A0EB261B4CA6F9DAFDDDAA584229F050') { throw 'Helper changed since review.' }
if (Test-Path -LiteralPath $root) {
    $existing=Get-Item -LiteralPath $root -Force
    if (($existing.Attributes -band [IO.FileAttributes]::ReparsePoint) -or @(Get-ChildItem -LiteralPath $root -Force).Count) { throw 'Install directory is not empty or is redirected; preserve for review.' }
}
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'Task already exists; preserve for review.' }
$before=(& powercfg.exe /requestsoverride) -join "`n"
if ($LASTEXITCODE -ne 0) { throw 'Cannot read overrides.' }
if ($before -match '(?i)Antigravity\.exe' -and $before -notmatch '(?im)^Antigravity\.exe\s+DISPLAY\s*$') { throw 'Unexpected Antigravity override; preserve it.' }
$scheme='381b4222-f694-41f0-9685-ff5bb260df2e'
$savedFast=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'fast-lock-before.json') -Raw | ConvertFrom-Json
if ($savedFast.Scheme -ne $scheme -or $savedFast.LockDisplayAcSeconds -ne 30 -or -not $savedFast.OriginalAntigravityOverrideAbsent) { throw 'Unexpected earlier backup.' }
New-Item -ItemType Directory -Path $root -Force | Out-Null
$acl=New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true,$false)
$acl.SetOwner([Security.Principal.SecurityIdentifier]::new('S-1-5-32-544'))
foreach($entry in @(@('S-1-5-18','FullControl'),@('S-1-5-32-544','FullControl'),@($sid,'ReadAndExecute'))) {
    $rule=[Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($entry[0]),$entry[1],'ContainerInherit,ObjectInherit','None','Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $root -AclObject $acl
Write-Output 'Directory protected.'
Copy-Item -LiteralPath $binary -Destination (Join-Path $root 'AlexDisplayPriority.exe')
$inbox=Join-Path $root 'requests'
New-Item -ItemType Directory -Path $inbox | Out-Null
$inboxAcl=Get-Acl -LiteralPath $inbox
$inboxAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]::new($sid),'Modify','ContainerInherit,ObjectInherit','None','Allow'))
Set-Acl -LiteralPath $inbox -AclObject $inboxAcl
$request=Join-Path $inbox 'request.txt'
[IO.File]::WriteAllLines((Join-Path $root 'settings.txt'),@($sid,$request),[Text.UTF8Encoding]::new($false))
$xml=@"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.3" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
 <RegistrationInfo><Description>Alex temporary display priority; restores Antigravity on unlock. No PIN or network access.</Description></RegistrationInfo>
 <Triggers>
  <LogonTrigger><Enabled>true</Enabled><UserId>$sid</UserId></LogonTrigger>
  <SessionStateChangeTrigger><Enabled>true</Enabled><StateChange>SessionUnlock</StateChange><UserId>$sid</UserId></SessionStateChangeTrigger>
 </Triggers>
 <Principals><Principal id="Author"><UserId>$sid</UserId><LogonType>InteractiveToken</LogonType><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
 <Settings><MultipleInstancesPolicy>Queue</MultipleInstancesPolicy><DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries><StopIfGoingOnBatteries>false</StopIfGoingOnBatteries><AllowHardTerminate>true</AllowHardTerminate><StartWhenAvailable>true</StartWhenAvailable><RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable><AllowStartOnDemand>true</AllowStartOnDemand><Enabled>true</Enabled><Hidden>true</Hidden><ExecutionTimeLimit>PT0S</ExecutionTimeLimit><Priority>7</Priority></Settings>
 <Actions Context="Author"><Exec><Command>$root\AlexDisplayPriority.exe</Command><Arguments>--run</Arguments></Exec></Actions>
</Task>
"@
Register-ScheduledTask -TaskName $taskName -Xml $xml | Out-Null
$scheduler=New-Object -ComObject 'Schedule.Service'
$scheduler.Connect()
$task=$scheduler.GetFolder('\').GetTask($taskName)
$task.SetSecurityDescriptor(('O:BAG:BAD:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GRGX;;;'+$sid+')'),0)
# Retire the permanent override from the previous version; no other process is changed.
if ($before -match '(?im)^Antigravity\.exe\s+DISPLAY\s*$') {
    & powercfg.exe /requestsoverride PROCESS Antigravity.exe
    if($LASTEXITCODE -ne 0){throw 'Cannot retire the previous permanent override.'}
}
& powercfg.exe /setacvalueindex $scheme SUB_VIDEO VIDEOCONLOCK 30
if($LASTEXITCODE -ne 0){throw 'Cannot restore normal lock-display timeout.'}
if ((& powercfg.exe /getactivescheme) -match $scheme) {
    & powercfg.exe /setactive $scheme
    if($LASTEXITCODE -ne 0){throw 'Cannot apply normal timeout.'}
}
$result=[ordered]@{InstalledAt=(Get-Date).ToString('o');Root=$root;Task=$taskName;Principal=$sid;RunLevel='HighestAvailable';NormalLockDisplayAcSeconds=30;Overrides=((& powercfg.exe /requestsoverride)-join "`n");BinarySha256=(Get-FileHash -LiteralPath (Join-Path $root 'AlexDisplayPriority.exe') -Algorithm SHA256).Hash}
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $root 'installation.json') -Encoding utf8
$result | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'display-priority-installation.json') -Encoding utf8
Stop-Transcript | Out-Null
