param(
    [Parameter(Mandatory=$true)][string]$UserSid,
    [Parameter(Mandatory=$true)][ValidatePattern('^[0-9A-Fa-f]{64}$')][string]$ExpectedSha256
)
$ErrorActionPreference='Stop'
$target='D:\AlexUnlock-System'
$result=Join-Path $PSScriptRoot 'install-result.txt'
try {
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $principal=New-Object Security.Principal.WindowsPrincipal($identity)
    if(-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Administrator required.' }
    $null=New-Object Security.Principal.SecurityIdentifier($UserSid)
    if($UserSid -notmatch '^S-1-5-21-') { throw 'Expected a local signed-in user SID.' }
    $source=Join-Path $PSScriptRoot 'AlexUnlock.exe'
    if((Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash -ne $ExpectedSha256) { throw 'Binary verification failed.' }
    $existing=Get-Service -Name AlexUnlock -ErrorAction SilentlyContinue
    if(Test-Path -LiteralPath $target) {
        $item=Get-Item -LiteralPath $target -Force
        if($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Install directory cannot be a link.' }
        if(-not $existing) { throw 'Unmanaged install directory exists; refusing to overwrite.' }
        if((Get-Acl -LiteralPath $target).GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-18') { throw 'Install directory owner changed.' }
        $svc=Get-CimInstance Win32_Service -Filter "Name='AlexUnlock'"
        if($svc.PathName.Trim('"') -ne "$target\AlexUnlock.exe") { throw 'Unexpected existing service binary.' }
        Stop-Service -Name AlexUnlock -Force
    } else {
        # Parent must not permit ordinary users to delete/replace protected children.
        foreach($rule in (Get-Acl -LiteralPath 'D:\').Access) {
            $sid=$rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
            if($sid -in @('S-1-1-0','S-1-5-11','S-1-5-32-545',$UserSid) -and
                $rule.AccessControlType -eq 'Allow' -and ([int]$rule.FileSystemRights -band 64)) { throw 'D drive parent permits child replacement.' }
        }
        New-Item -ItemType Directory -Path $target | Out-Null
    }
    $acl=New-Object Security.AccessControl.DirectorySecurity
    $acl.SetAccessRuleProtection($true,$false)
    $acl.SetOwner((New-Object Security.Principal.SecurityIdentifier('S-1-5-32-544')))
    foreach($entry in @(@('S-1-5-18','FullControl'),@('S-1-5-32-544','FullControl'),@('S-1-5-32-545','ReadAndExecute'))) {
        $rule=New-Object Security.AccessControl.FileSystemAccessRule((New-Object Security.Principal.SecurityIdentifier($entry[0])),$entry[1],'ContainerInherit,ObjectInherit','None','Allow')
        $acl.AddAccessRule($rule)
    }
    Set-Acl -LiteralPath $target -AclObject $acl
    & "$env:SystemRoot\System32\icacls.exe" $target /setowner '*S-1-5-18' | Out-Null
    if($LASTEXITCODE -ne 0) { throw 'Could not protect directory owner.' }
    foreach($name in @('AlexUnlock.exe','user.sid','attempts.txt')) {
        $path=Join-Path $target $name
        if((Test-Path -LiteralPath $path) -and ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Install file cannot be a link.' }
    }
    Copy-Item -LiteralPath $source -Destination "$target\AlexUnlock.exe" -Force
    [IO.File]::WriteAllText("$target\user.sid",$UserSid,[Text.Encoding]::ASCII)
    if(-not (Test-Path -LiteralPath "$target\attempts.txt")) { [IO.File]::WriteAllText("$target\attempts.txt",'',[Text.Encoding]::ASCII) }
    if(-not $existing) {
        New-Service -Name AlexUnlock -BinaryPathName '"D:\AlexUnlock-System\AlexUnlock.exe"' -DisplayName 'Alex Unlock (paired phone)' -StartupType Automatic -Description 'Receives one PIN attempt from the paired Alex user over a local named pipe; no network listener.' | Out-Null
    }
    Start-Service -Name AlexUnlock
    (Get-Service AlexUnlock).WaitForStatus('Running',[TimeSpan]::FromSeconds(10))
    [IO.File]::WriteAllText($result,'installed; service running; no PIN sent',[Text.Encoding]::UTF8)
} catch {
    [IO.File]::WriteAllText($result,'installation failed: '+$_.Exception.Message,[Text.Encoding]::UTF8)
    exit 1
}
