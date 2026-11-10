<#
.SYNOPSIS
    Polaczenie QGIS Desktop z baza Sophii przez tunel SSH (usluga PostgreSQL "sophia").

.DESCRIPTION
    1. Zapisuje sekcje [sophia] w %APPDATA%\postgresql\.pg_service.conf
       (domyslne miejsce pliku uslug libpq na Windows; QGIS czyta je sam).
       Bez hasla - dzieki temu warstwy w projekcie maja w zrodle tylko "service=sophia"
       i dzialaja bez zmian na serwerze (tam ta sama nazwa uslugi wskazuje kontener db).
    2. Pyta o haslo bazy (POSTGRES_PASSWORD z /opt/sophia/.env) i zapisuje je
       w %APPDATA%\postgresql\pgpass.conf - libpq bierze je stamtad automatycznie.
       Haslo nie trafia do projektu QGIS ani do ustawien QGIS.
    3. -StartTunnel: uruchamia w tle tunel "ssh -N sophia-db" (localhost:15432 -> serwer:5432).
    4. -Autostart: tunel startuje sam po zalogowaniu do Windows (zadanie Harmonogramu zadan
       "Sophia tunel bazy") i wznawia polaczenie po zerwaniu (uspienie, zmiana sieci).
       Wymaga klucza SSH bez hasla albo dzialajacego ssh-agent z dodanym kluczem.
       -RemoveAutostart: usuwa zadanie i zatrzymuje tunel.

    Skrypt mozna uruchamiac wielokrotnie (podmienia swoje wpisy).

.EXAMPLE
    .\setup-pg.ps1                               # plik uslug + pytanie o haslo
    .\setup-pg.ps1 -SkipPassword -Autostart      # tunel zawsze w tle, takze po restarcie
    .\setup-pg.ps1 -SkipPassword -StartTunnel    # jednorazowo uruchom tunel w tle
    .\setup-pg.ps1 -SkipPassword -RemoveAutostart
#>
[CmdletBinding()]
param(
    [string]$Service = "sophia",
    [string]$HostName = "localhost",
    [int]$Port = 15432,
    [string]$Database = "sophia",
    [string]$User = "sophia",
    [string]$TunnelHost = "sophia-db",
    [switch]$SkipPassword,
    [switch]$StartTunnel,
    [switch]$Autostart,
    [switch]$RemoveAutostart
)

$ErrorActionPreference = "Stop"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$pgDir = Join-Path $env:APPDATA "postgresql"
$serviceFile = Join-Path $pgDir ".pg_service.conf"
$passFile = Join-Path $pgDir "pgpass.conf"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

if (-not (Test-Path $pgDir)) { New-Item -ItemType Directory $pgDir | Out-Null }

# ------------------------------------------------------------------ 1. plik uslug
Step "Usluga [$Service] w $serviceFile"
$section = @"
[$Service]
host=$HostName
port=$Port
dbname=$Database
user=$User
sslmode=disable
"@
$text = if (Test-Path $serviceFile) { [IO.File]::ReadAllText($serviceFile) } else { "" }
# usun poprzednia sekcje [$Service] (do nastepnego naglowka albo konca pliku)
$pattern = "(?ms)^\[" + [regex]::Escape($Service) + "\]\s*$.*?(?=^\[|\z)"
$text = [regex]::Replace($text, $pattern, "").TrimEnd()
$text = if ($text) { "$text`n`n$section`n" } else { "$section`n" }
[IO.File]::WriteAllText($serviceFile, ($text -replace "`r", ""), $utf8NoBom)
Ok "Zapisano (bez hasla; host=$HostName port=$Port dbname=$Database user=$User)"

# ------------------------------------------------------------------ 2. haslo
if (-not $SkipPassword) {
    Step "Haslo do bazy -> $passFile"
    Write-Host "    Haslo = POSTGRES_PASSWORD z /opt/sophia/.env na serwerze (ssh sophia 'grep POSTGRES_PASSWORD /opt/sophia/.env')" -ForegroundColor Gray
    $secure = Read-Host "    Haslo uzytkownika $User" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
    if (-not $plain) { throw "Puste haslo - przerwano" }
    $escaped = $plain.Replace("\", "\\").Replace(":", "\:")
    $prefix = "${HostName}:${Port}:${Database}:${User}:"
    $lines = if (Test-Path $passFile) { @(Get-Content $passFile | Where-Object { -not $_.StartsWith($prefix) }) } else { @() }
    $lines += "$prefix$escaped"
    [IO.File]::WriteAllText($passFile, (($lines -join "`n") + "`n"), $utf8NoBom)
    $plain = $null
    # tylko biezacy uzytkownik moze czytac plik z haslem
    & icacls.exe $passFile /inheritance:r /grant:r "$($env:USERNAME):(R,W)" | Out-Null
    Ok "Zapisano (dostep tylko dla $env:USERNAME)"
}

# ------------------------------------------------------------------ 3. tunel
# Szybki test portu (Test-NetConnection przy zamknietym porcie czeka kilkanascie sekund)
$open = {
    $c = New-Object Net.Sockets.TcpClient
    try { $c.ConnectAsync("127.0.0.1", $Port).Wait(1000) -and $c.Connected } catch { $false } finally { $c.Close() }
}
$taskName = "Sophia tunel bazy ($TunnelHost)"
# Petla tunelu lezy w repo obok tego skryptu (nie generujemy plikow w %APPDATA%)
$loopFile = Join-Path $PSScriptRoot "sophia-tunnel.ps1"

# Procesy ssh obslugujace ten tunel (uruchomione recznie albo przez petle autostartu)
function Get-TunnelSsh {
    Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" |
        Where-Object { $_.CommandLine -match "-N\b" -and $_.CommandLine -match [regex]::Escape($TunnelHost) }
}
function Get-TunnelLoop {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($loopFile) }
}

if ($RemoveAutostart) {
    Step "Usuwanie autostartu tunelu"
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    Get-TunnelLoop | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-TunnelSsh | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Ok "Zadanie usuniete, tunel zatrzymany"
}

if ($Autostart) {
    Step "Autostart tunelu: zadanie '$taskName'"
    if (-not (Test-Path $loopFile)) { throw "Brak $loopFile" }
    Warn "Zadanie wskazuje $loopFile - po przeniesieniu repo uruchom -Autostart ponownie"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$loopFile`" -TunnelHost $TunnelHost -Port $Port"
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
        -Principal $principal -Description "Tunel SSH localhost:$Port -> baza Sophii (setup-pg.ps1)" -Force | Out-Null
    Ok "Zadanie zarejestrowane (start po zalogowaniu)"

    # Reczny tunel z -StartTunnel zastepujemy petla, ktora sama wznawia polaczenie
    Get-TunnelSsh | Where-Object { -not (Get-TunnelLoop) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-ScheduledTask -TaskName $taskName
    $ok = $false
    for ($i = 0; $i -lt 20 -and -not $ok; $i++) { Start-Sleep -Seconds 1; $ok = & $open }
    if ($ok) { Ok "Tunel dziala (localhost:$Port)" }
    else { Warn "Port $Port nie odpowiada - sprawdz: ssh -o BatchMode=yes $TunnelHost true" }
    $StartTunnel = $false
}

if ($StartTunnel) {
    Step "Tunel SSH $TunnelHost (localhost:$Port)"
    if (& $open) {
        Ok "Port $Port juz otwarty - tunel dziala"
    } else {
        Start-Process ssh.exe -ArgumentList "-N", "-o", "ExitOnForwardFailure=yes", "-o", "ServerAliveInterval=60", $TunnelHost -WindowStyle Hidden
        $ok = $false
        for ($i = 0; $i -lt 15 -and -not $ok; $i++) { Start-Sleep -Seconds 1; $ok = & $open }
        if ($ok) { Ok "Tunel dziala w tle (zamkniecie: Stop-Process -Name ssh)" }
        else { Warn "Port $Port nie odpowiada - sprawdz recznie: ssh -N $TunnelHost" }
    }
}

# ------------------------------------------------------------------ test
$psql = @("C:\OSGeo4W\bin\psql.exe", "C:\Program Files\PostgreSQL\17\bin\psql.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if ((& $open) -and $psql -and -not $SkipPassword) {
    Step "Test polaczenia (service=$Service)"
    $env:PGSERVICEFILE = $serviceFile
    $out = & { $ErrorActionPreference = "Continue"; & $psql "service=$Service" -w -At -c "select current_user || ' @ ' || current_database() || ', PostGIS ' || postgis_lib_version()" 2>&1 }
    if ($LASTEXITCODE -eq 0) { Ok "$out" } else { Warn "$out" }
} elseif (-not (& $open)) {
    Warn "Tunel nie dziala - przed praca w QGIS uruchom: .\setup-pg.ps1 -SkipPassword -StartTunnel  (albo: ssh -N $TunnelHost)"
}

Write-Host "`nGotowe. W QGIS: Przegladarka -> PostgreSQL -> Nowe polaczenie -> Usluga: $Service (reszta pol pusta)." -ForegroundColor Cyan
