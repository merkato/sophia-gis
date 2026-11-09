<#
.SYNOPSIS
    Przygotowuje Windows do logowania na serwer Sophii kluczem SSH.

.DESCRIPTION
    1. Sprawdza klienta OpenSSH (wbudowany w Windows 10/11).
    2. Wlacza usluge ssh-agent (wymaga uruchomienia jako Administrator - tylko raz).
    3. Generuje klucz ed25519 (zapyta o haslo do klucza - USTAW JE).
    4. Dodaje klucz do agenta (haslo podajesz raz, agent pamieta je po restarcie).
    5. Dopisuje do ~/.ssh/config wpis "Host sophia" -> potem wystarczy: ssh sophia
    6. Kopiuje klucz publiczny do schowka (do wklejenia w panelu OVH przy instalacji VPS).
    7. Opcjonalnie (-CopyToServer) wgrywa klucz na serwer, ktory juz dziala z haslem.
    8. Opcjonalnie (-ConfigureGit) ustawia Git, by uzywal tego samego ssh/agenta.

    Skrypt mozna uruchamiac wielokrotnie - kazdy krok sprawdza, czy nie jest juz zrobiony.

.EXAMPLE
    # Krok 1 (raz, PowerShell "Uruchom jako administrator"): tylko wlaczenie agenta
    .\setup-ssh.ps1 -EnableAgentOnly

    # Krok 2 (zwykly PowerShell): klucz + config; serwer jeszcze nie istnieje
    .\setup-ssh.ps1

    # Po zakupie VPS: uzupelnij adres w configu
    .\setup-ssh.ps1 -Server 51.75.12.34 -User ubuntu

    # Serwer zainstalowany bez klucza (logowanie haslem) - wgraj klucz
    .\setup-ssh.ps1 -Server 51.75.12.34 -User ubuntu -CopyToServer
#>
[CmdletBinding()]
param(
    [string]$Server = "",
    [string]$User = "ubuntu",
    [string]$HostAlias = "sophia",
    [string]$KeyName = "id_ed25519_sophia",
    [switch]$CopyToServer,
    [switch]$ConfigureGit,
    [switch]$EnableAgentOnly
)

$ErrorActionPreference = "Stop"
$sshDir = Join-Path $HOME ".ssh"
$keyPath = Join-Path $sshDir $KeyName
$pubPath = "$keyPath.pub"
$configPath = Join-Path $sshDir "config"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)   # OpenSSH nie lubi BOM w configu

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Ok($msg) { Write-Host "    OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    !!  $msg" -ForegroundColor Yellow }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

# ------------------------------------------------------------------ 1. OpenSSH
Step "Klient OpenSSH"
$ssh = Get-Command ssh.exe -ErrorAction SilentlyContinue
if (-not $ssh) {
    if ($isAdmin) {
        Add-WindowsCapability -Online -Name OpenSSH.Client~~~~0.0.1.0 | Out-Null
        Ok "Zainstalowano klienta OpenSSH - uruchom skrypt ponownie w nowym oknie"
        return
    }
    throw "Brak ssh.exe. Uruchom jako Administrator albo: Ustawienia > System > Funkcje opcjonalne > Klient OpenSSH"
}
Ok "$($ssh.Source) ($((& ssh.exe -V 2>&1) -join ' '))"

# ------------------------------------------------------------------ 2. ssh-agent
Step "Usluga ssh-agent"
$agent = Get-Service ssh-agent -ErrorAction SilentlyContinue
if (-not $agent) { throw "Brak uslugi ssh-agent (niepelna instalacja OpenSSH)" }
if ($agent.StartType -ne "Automatic") {
    if ($isAdmin) {
        Set-Service ssh-agent -StartupType Automatic
        Ok "Ustawiono uruchamianie automatyczne"
    } else {
        Warn "ssh-agent jest wylaczony ($($agent.StartType)). Uruchom raz jako Administrator:"
        Warn "    .\setup-ssh.ps1 -EnableAgentOnly"
        Warn "Kontynuuje bez agenta - haslo do klucza bedzie potrzebne przy kazdym polaczeniu."
    }
}
$agent = Get-Service ssh-agent
if ($agent.StartType -eq "Automatic" -and $agent.Status -ne "Running") {
    Start-Service ssh-agent
    $agent = Get-Service ssh-agent
}
if ($agent.Status -eq "Running") { Ok "ssh-agent dziala" }
if ($EnableAgentOnly) {
    Write-Host "`nGotowe. Teraz uruchom skrypt w ZWYKLYM PowerShellu (bez -EnableAgentOnly)." -ForegroundColor Cyan
    return
}
if ($isAdmin) {
    Warn "Uruchomiono jako Administrator - klucz powstanie w profilu tego konta ($HOME)."
}

# ------------------------------------------------------------------ 3. klucz
Step "Klucz $keyPath"
if (-not (Test-Path $sshDir)) { New-Item -ItemType Directory $sshDir | Out-Null }
if (Test-Path $keyPath) {
    Ok "Klucz juz istnieje - nie nadpisuje"
} else {
    Write-Host "    Za chwile ssh-keygen zapyta o haslo do klucza. Ustaw je (min. 12 znakow)." -ForegroundColor Gray
    Write-Host "    Agent zapamieta je po pierwszym uzyciu, wiec nie bedziesz go wpisywac codziennie." -ForegroundColor Gray
    & ssh-keygen.exe -t ed25519 -a 100 -C "$env:USERNAME@$env:COMPUTERNAME-sophia" -f $keyPath
    if ($LASTEXITCODE -ne 0) { throw "ssh-keygen zakonczyl sie bledem" }
    Ok "Utworzono klucz"
}

# ------------------------------------------------------------------ 4. agent
if ($agent.Status -eq "Running") {
    Step "Dodanie klucza do agenta"
    $fingerprint = ((& ssh-keygen.exe -lf $pubPath) -split " ")[1]
    $loaded = (& ssh-add.exe -l 2>$null) -join "`n"
    if ($loaded -like "*$fingerprint*") {
        Ok "Klucz juz jest w agencie"
    } else {
        & ssh-add.exe $keyPath
        if ($LASTEXITCODE -eq 0) { Ok "Dodano (agent pamieta klucz takze po restarcie Windows)" }
    }
}

# ------------------------------------------------------------------ 5. ~/.ssh/config
Step "Wpis 'Host $HostAlias' w $configPath"
$hostName = if ($Server) { $Server } else { "ADRES_SERWERA" }
$block = @"

Host $HostAlias
    HostName $hostName
    User $User
    IdentityFile ~/.ssh/$KeyName
    IdentitiesOnly yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
    # Tunel do PostGIS dla QGIS Desktop: ssh -N sophia-db  (potem localhost:15432)
Host $HostAlias-db
    HostName $hostName
    User $User
    IdentityFile ~/.ssh/$KeyName
    IdentitiesOnly yes
    LocalForward 15432 127.0.0.1:5432
    ServerAliveInterval 60
"@
$config = if (Test-Path $configPath) { [IO.File]::ReadAllText($configPath) } else { "" }
if ($config -match "(?m)^Host\s+$([regex]::Escape($HostAlias))\s*$") {
    if ($Server -and $config -match "ADRES_SERWERA") {
        $config = $config -replace "ADRES_SERWERA", $Server
        [IO.File]::WriteAllText($configPath, $config, $utf8NoBom)
        Ok "Uzupelniono adres serwera: $Server"
    } else {
        Ok "Wpis juz istnieje - nie zmieniam (edytuj recznie, jesli trzeba)"
    }
} else {
    if (Test-Path $configPath) { Copy-Item $configPath "$configPath.bak" -Force }
    [IO.File]::AppendAllText($configPath, $block, $utf8NoBom)
    Ok "Dopisano wpisy '$HostAlias' i '$HostAlias-db' (kopia: config.bak)"
    if (-not $Server) { Warn "Po zakupie VPS uruchom: .\setup-ssh.ps1 -Server <IP>" }
}

# ------------------------------------------------------------------ 6. klucz publiczny
Step "Klucz publiczny"
$pub = (Get-Content $pubPath -Raw).Trim()
try { Set-Clipboard -Value $pub; Ok "Skopiowany do schowka" } catch { Warn "Nie udalo sie skopiowac do schowka" }
Write-Host "    $pub" -ForegroundColor White
Write-Host "    Wklej go w panelu OVH: przy zamawianiu/reinstalacji VPS (pole 'Klucz SSH')" -ForegroundColor Gray
Write-Host "    albo w Panel > Public Cloud/Bare Metal > Klucze SSH." -ForegroundColor Gray

# ------------------------------------------------------------------ 7. wgranie na serwer
if ($CopyToServer) {
    if (-not $Server) { throw "-CopyToServer wymaga -Server" }
    Step "Wgrywanie klucza na $User@$Server (zapyta o haslo uzytkownika na serwerze)"
    $remote = "umask 077; mkdir -p ~/.ssh; touch ~/.ssh/authorized_keys; " +
              "grep -qxF '$pub' ~/.ssh/authorized_keys || echo '$pub' >> ~/.ssh/authorized_keys"
    & ssh.exe -o IdentitiesOnly=yes -o PreferredAuthentications=password,keyboard-interactive "$User@$Server" $remote
    if ($LASTEXITCODE -ne 0) { throw "Nie udalo sie wgrac klucza" }
    Ok "Klucz wgrany. Test:"
    & ssh.exe -o BatchMode=yes $HostAlias "echo '    OK  logowanie kluczem dziala na' `$(hostname)"
}

# ------------------------------------------------------------------ 8. Git
if ($ConfigureGit) {
    Step "Git -> ssh z Windows (wspolny agent)"
    & git config --global core.sshCommand "C:/Windows/System32/OpenSSH/ssh.exe"
    Ok "core.sshCommand ustawiony (Git uzyje klucza z ssh-agent Windows)"
}

Write-Host "`nGotowe. Polaczenie: ssh $HostAlias" -ForegroundColor Cyan
