<#
.SYNOPSIS
    Tunel SSH do bazy Sophii, wznawiany po zerwaniu. Uruchamiany przez zadanie
    Harmonogramu zadan (setup-pg.ps1 -Autostart); mozna tez uruchomic recznie.
#>
param(
    [string]$TunnelHost = "sophia-db",
    [int]$Port = 15432
)

# Jedna instancja na port
$mutex = New-Object System.Threading.Mutex($false, "Local\SophiaTunnel_$Port")
if (-not $mutex.WaitOne(0)) { exit }

$ssh = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
while ($true) {
    & $ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
        -o ServerAliveCountMax=3 -o ConnectTimeout=15 $TunnelHost
    Start-Sleep -Seconds 10
}
