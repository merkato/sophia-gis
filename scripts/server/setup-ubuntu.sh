#!/usr/bin/env bash
# Pierwsza konfiguracja świeżego VPS z Ubuntu 24.04 / 26.04 LTS pod Sophię.
#
#   scp scripts/server/setup-ubuntu.sh sophia:      # z Windows, po skonfigurowaniu klucza
#   ssh sophia
#   sudo bash setup-ubuntu.sh                       # opcje: --user ubuntu --swap 2G --tz Europe/Warsaw
#
# Skrypt jest idempotentny — można go uruchomić ponownie.
# Logowanie hasłem i na roota jest wyłączane TYLKO, jeśli użytkownik ma już klucz w authorized_keys
# (ochrona przed odcięciem sobie dostępu).
set -euo pipefail

APP_USER="${SUDO_USER:-ubuntu}"
SWAP_SIZE="2G"
TZ_NAME="Europe/Warsaw"
APP_DIR="/opt/sophia"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --user) APP_USER="$2"; shift 2 ;;
    --swap) SWAP_SIZE="$2"; shift 2 ;;
    --tz)   TZ_NAME="$2"; shift 2 ;;
    --dir)  APP_DIR="$2"; shift 2 ;;
    *) echo "Nieznana opcja: $1" >&2; exit 1 ;;
  esac
done

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[32mOK\033[0m  %s\n' "$*"; }
warn() { printf '    \033[33m!!\033[0m  %s\n' "$*"; }

[[ $EUID -eq 0 ]] || { echo "Uruchom przez sudo." >&2; exit 1; }
id "$APP_USER" &>/dev/null || { echo "Brak użytkownika $APP_USER (użyj --user)." >&2; exit 1; }
. /etc/os-release
[[ "$ID" == "ubuntu" ]] || warn "To nie jest Ubuntu ($PRETTY_NAME) — kontynuuję na własne ryzyko"
export DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------- system
step "Aktualizacja systemu i pakiety bazowe"
apt-get update -q
apt-get -y -q -o Dpkg::Options::="--force-confold" upgrade
apt-get -y -q install ca-certificates curl gnupg ufw fail2ban unattended-upgrades \
  git rsync htop ncdu jq
ok "Pakiety zainstalowane"

step "Strefa czasowa: $TZ_NAME"
timedatectl set-timezone "$TZ_NAME"
ok "$(date)"

# ---------------------------------------------------------------- swap
step "Plik wymiany ($SWAP_SIZE)"
if swapon --show | grep -q .; then
  ok "Swap już jest: $(swapon --show --noheadings | awk '{print $1, $3}')"
else
  fallocate -l "$SWAP_SIZE" /swapfile
  chmod 600 /swapfile
  mkswap /swapfile >/dev/null
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  ok "Utworzono /swapfile"
fi
cat > /etc/sysctl.d/90-sophia.conf <<'EOF'
# Swap tylko awaryjnie; pamięć podręczna plików (rastry) ważniejsza niż wymiana
vm.swappiness = 10
vm.vfs_cache_pressure = 50
EOF
sysctl -q --system
ok "swappiness=10"

# ---------------------------------------------------------------- Docker
step "Docker (oficjalne repozytorium)"
if ! command -v docker &>/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get -y -q install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
mkdir -p /etc/docker
if [[ ! -f /etc/docker/daemon.json ]]; then
  # Rotacja logów kontenerów — bez tego logi QGIS Server potrafią zapełnić dysk
  cat > /etc/docker/daemon.json <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "live-restore": true
}
EOF
  systemctl restart docker
fi
systemctl enable --now docker >/dev/null 2>&1
usermod -aG docker "$APP_USER"
ok "$(docker --version); $(docker compose version)"
ok "$APP_USER w grupie docker (zaloguj się ponownie, by zadziałało)"

# ---------------------------------------------------------------- firewall
step "Zapora ufw: tylko SSH, HTTP, HTTPS"
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw allow 443/udp >/dev/null      # HTTP/3
ufw --force enable >/dev/null
ok "$(ufw status | head -1)"
warn "Docker omija ufw dla portów publikowanych w compose — dlatego PostGIS jest tylko na 127.0.0.1"

# ---------------------------------------------------------------- fail2ban
step "fail2ban dla SSH"
cat > /etc/fail2ban/jail.d/sophia.local <<'EOF'
[sshd]
enabled = true
backend = systemd
maxretry = 5
findtime = 10m
bantime = 1h
EOF
systemctl enable --now fail2ban >/dev/null 2>&1
systemctl restart fail2ban
ok "fail2ban aktywny"

# ---------------------------------------------------------------- aktualizacje automatyczne
step "Automatyczne aktualizacje bezpieczeństwa"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat > /etc/apt/apt.conf.d/52sophia-unattended <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:30";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades >/dev/null 2>&1
ok "Włączone (restart, jeśli wymagany, o 04:30)"

# ---------------------------------------------------------------- SSH
step "Utwardzenie SSH"
AUTH_KEYS="$(getent passwd "$APP_USER" | cut -d: -f6)/.ssh/authorized_keys"
if [[ -s "$AUTH_KEYS" ]] && grep -qE '^(ssh-ed25519|ssh-rsa|ecdsa-)' "$AUTH_KEYS"; then
  # 00- ma pierwszeństwo przed 50-cloud-init.conf (sshd bierze pierwszą znalezioną wartość)
  cat > /etc/ssh/sshd_config.d/00-sophia.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
PubkeyAuthentication yes
MaxAuthTries 3
X11Forwarding no
AllowTcpForwarding local
EOF
  sshd -t
  systemctl reload ssh 2>/dev/null || systemctl restart ssh
  ok "Logowanie tylko kluczem, root wyłączony"
  warn "NIE zamykaj tej sesji, dopóki w drugim oknie nie sprawdzisz: ssh sophia"
else
  warn "$APP_USER nie ma klucza w $AUTH_KEYS — pomijam wyłączenie haseł."
  warn "Na Windows uruchom: scripts\\windows\\setup-ssh.ps1 -Server <IP> -CopyToServer, potem ten skrypt ponownie."
fi

# ---------------------------------------------------------------- katalog aplikacji
step "Katalog aplikacji $APP_DIR"
mkdir -p "$APP_DIR" "$APP_DIR-backups"
chown "$APP_USER:$APP_USER" "$APP_DIR" "$APP_DIR-backups"
ok "Gotowy (właściciel: $APP_USER)"

cat <<EOF

$(printf '\033[1;32mSerwer gotowy.\033[0m') Dalej (jako $APP_USER, po ponownym zalogowaniu):

  1. Repo:             git clone https://github.com/merkato/sophia-gis.git $APP_DIR
  2. Konfiguracja:      cd $APP_DIR && cp .env.example .env && nano .env
                        echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml' >> .env
                        (hasło w config/pg_service.conf = POSTGRES_PASSWORD)
  3. DNS:               rekord A domeny -> $(curl -fsS4 --max-time 5 https://ifconfig.me 2>/dev/null || echo '<IP serwera>')
  4. Start:             docker compose up -d --build
  5. Kopie zapasowe:    crontab -e  ->  15 3 * * * $APP_DIR/scripts/server/backup.sh >> $APP_DIR-backups/backup.log 2>&1
EOF
