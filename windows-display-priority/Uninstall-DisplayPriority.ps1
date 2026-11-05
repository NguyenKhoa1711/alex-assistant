# Close Alex before running. Restores only this helper's temporary power changes.
$ErrorActionPreference='Stop'
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator required.' }
$root='D:\AlexPowerPriority-System'
if ((Get-Item -LiteralPath $root).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Unexpected redirected installation.' }
$request=Join-Path $root 'requests\request.txt'
if(Test-Path -LiteralPath $request){Remove-Item -LiteralPath $request}
$deadline=(Get-Date).AddSeconds(6)
while((Get-Process AlexDisplayPriority -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline){Start-Sleep -Milliseconds 200}
if(Get-Process AlexDisplayPriority -ErrorAction SilentlyContinue){throw 'Helper is still running; leave task and recovery journal intact.'}
& (Join-Path $root 'AlexDisplayPriority.exe') --restore
if($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath (Join-Path $root 'active.json'))){throw 'Restore has not completed; preserve recovery task.'}
Unregister-ScheduledTask -TaskName 'Alex Display Priority' -Confirm:$false -ErrorAction SilentlyContinue
Write-Output 'Temporary policy restored; task removed. Protected files retained for recovery.'
