param(
    [Parameter(Mandatory=$true)][string]$PetRoot,
    [int]$ExternalPort = 8768,
    [int]$LocalPort = 8769
)
$ErrorActionPreference = 'Stop'
$ts = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'
if (!(Test-Path -LiteralPath $ts)) { throw 'Tailscale is not installed.' }
if ($ExternalPort -lt 1024 -or $ExternalPort -gt 65535 -or $LocalPort -lt 1024 -or $LocalPort -gt 65535) {
    throw 'Unexpected port.'
}
$resolvedRoot = (Resolve-Path -LiteralPath $PetRoot).Path
if (!(Test-Path -LiteralPath (Join-Path $resolvedRoot 'pet\mobile.py'))) { throw 'Alex directory not found.' }
$state = (& $ts status --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $state.BackendState -ne 'Running') {
    throw 'Sign in to Tailscale on this laptop first. Do not send passwords to chat.'
}
$addresses = @($state.TailscaleIPs | Where-Object {
    $_ -match '^100\.(\d{1,3})\.\d{1,3}\.\d{1,3}$' -and [int]$Matches[1] -ge 64 -and [int]$Matches[1] -le 127
})
if ($addresses.Count -ne 1) { throw 'No unambiguous private Tailscale IPv4 address.' }
$address = $addresses[0]
$status = (& $ts serve status --json) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect existing Tailscale Serve configuration.' }
if ($status.AllowFunnel -and @($status.AllowFunnel.PSObject.Properties | Where-Object Value).Count) {
    throw 'Public Funnel is enabled. Review it separately before using Alex.'
}
$target = "127.0.0.1:$LocalPort"
$existing = $status.TCP.PSObject.Properties | Where-Object Name -eq "$ExternalPort"
if ($existing -and $existing.Value.TCPForward -ne $target) {
    throw 'That Tailscale port is already used by another service; it was not changed.'
}
$listener = [Net.Sockets.TcpClient]::new()
try { $listener.Connect('127.0.0.1', $LocalPort) }
catch { throw 'Alex private ingress is not running. Start the updated pet first.' }
finally { $listener.Dispose() }
# Raw TCP forwarding preserves the original Alex TLS certificate and pairing token.
# Serve is private to the tailnet. Do not use Funnel or TLS termination here.
& $ts serve --bg "--tcp=$ExternalPort" "tcp://127.0.0.1:$LocalPort"
if ($LASTEXITCODE -ne 0) { throw 'Tailscale Serve did not accept the configuration.' }
$verified = (& $ts serve status --json) | ConvertFrom-Json
$active = $verified.TCP.PSObject.Properties | Where-Object Name -eq "$ExternalPort"
if ($LASTEXITCODE -ne 0 -or !$active -or $active.Value.TCPForward -ne $target) {
    throw 'Private forwarding could not be verified. Pairing address was not changed.'
}
$file = Join-Path $resolvedRoot 'data\phone-remote-host.txt'
$temporary = $file + '.new'
[IO.File]::WriteAllText($temporary, $address, [Text.Encoding]::ASCII)
Move-Item -LiteralPath $temporary -Destination $file -Force
Write-Output 'Alex private forwarding is configured. Pair once using the new QR in Alex.'
