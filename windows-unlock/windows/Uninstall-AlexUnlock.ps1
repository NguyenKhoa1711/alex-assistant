# Run elevated. Preserve the protected binary and source for diagnosis; revoke execution first.
$ErrorActionPreference='Stop'
$service=Get-CimInstance Win32_Service -Filter "Name='AlexUnlock'"
if($service) {
    if($service.PathName.Trim('"') -ne 'D:\AlexUnlock-System\AlexUnlock.exe') { throw 'Unexpected service binary; refusing to change it.' }
    Stop-Service -Name AlexUnlock -Force
    & "$env:SystemRoot\System32\sc.exe" delete AlexUnlock
    if($LASTEXITCODE -ne 0) { throw 'Could not remove AlexUnlock service.' }
}
