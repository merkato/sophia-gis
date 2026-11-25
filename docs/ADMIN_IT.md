# Sophia WebGIS — instrukcja dla administratora IT

Co przygotować w sieci i w domenie organizacji oraz jak skonfigurować Sophię przy pierwszym uruchomieniu.
Szczegóły eksploatacji (aktualizacje, wtyczki, rastry, kopie zapasowe) — [SERVER.md](SERVER.md).

W przykładach: aplikacja pod adresem **`webgis.example.pl`**, serwer o adresie IP **`203.0.113.10`**,
domena organizacji **`example.pl`**. Zamień je na własne.

## 1. Serwer i sieć

- Linux z Dockerem (sprawdzony Ubuntu 24.04), od 4 vCPU / 8 GB RAM (więcej przy dużych rastrach); skrypt
  `scripts/server/setup-ubuntu.sh` przygotowuje świeży serwer (zapora, Docker, aktualizacje bezpieczeństwa).
- **Ruch przychodzący:** 443/TCP i 443/UDP (HTTPS, HTTP/3), 80/TCP (pobranie i odnawianie certyfikatu Let's
  Encrypt, przekierowanie na HTTPS), 22/TCP (administracja — najlepiej tylko z sieci administratora).
- **Ruch wychodzący:** 443/TCP (certyfikaty, usługi GUGiK: krajowa usługa działek, rejestr granic; obrazy Dockera),
  **25/TCP** — tylko gdy powiadomienia e-mail wysyła lekki serwer pocztowy Sophii (punkt 3); przy koncie SMTP
  organizacji zamiast 25 — port tego serwera (zwykle 465 albo 587).
- Na serwerze nie uruchamiaj innego proxy na portach 80/443 — Sophia ma własne (Caddy). Inne usługi na tym samym
  serwerze dołącza się przez Caddy Sophii (`proxy/sites/`).
- Jeśli użytkownicy pracują w sieci z filtrowaniem ruchu (proxy, zapora wychodząca), dopuść ruch HTTPS do
  `webgis.example.pl` — także kafle mapy (`/ows`) i API (`/api`) pod tym samym adresem.

## 2. DNS — adres aplikacji

| Rekord | Nazwa | Wartość | Kiedy |
|---|---|---|---|
| A | `webgis.example.pl` | `203.0.113.10` | **przed pierwszym startem** — inaczej certyfikat się nie pobierze |
| AAAA | `webgis.example.pl` | adres IPv6 serwera | tylko jeśli serwer ma IPv6 i zapora go przepuszcza |

Certyfikat HTTPS (Let's Encrypt) Caddy pobiera i odnawia sam — nie trzeba niczego wgrywać.

## 3. Poczta — powiadomienia e-mail

Sophia wysyła powiadomienia (np. zgłoszenie „Potrzeba wsparcia” w lustracji) na adresy zapisane w kontach
użytkowników. Tylko wysyła — nie odbiera poczty i nie ma skrzynek. Dwie możliwości:

**A. Lekki serwer pocztowy Sophii** (Postfix w kontenerze `mail`, podpis DKIM). Nadawca w osobnej poddomenie,
np. `powiadomienia@webgis.example.pl` — wpisy poniżej **nie zmieniają** poczty organizacji (`example.pl`).

| Rekord | Nazwa | Wartość |
|---|---|---|
| TXT (SPF) | `webgis.example.pl` | `v=spf1 ip4:203.0.113.10 -all` |
| TXT (DKIM) | `sophia._domainkey.webgis.example.pl` | `v=DKIM1; k=rsa; p=…` — klucz z serwera po pierwszym starcie (niżej) |
| TXT (DMARC) | `_dmarc.webgis.example.pl` | `v=DMARC1; p=quarantine; adkim=s; aspf=s; rua=mailto:it@example.pl` |
| PTR (rewers) | adres `203.0.113.10` | `webgis.example.pl` — ustawia się **u dostawcy serwera** (panel IP / „reverse DNS”), nie w strefie domeny |

Rekord MX nie jest potrzebny (poddomena nie odbiera poczty). Bez SPF, DKIM i PTR wiadomości trafiają do spamu
albo są odrzucane (np. Gmail, Microsoft 365).

**B. Konto SMTP organizacji** (np. Microsoft 365, Exchange, poczta u operatora domeny) — wiadomości wychodzą
z istniejącej skrzynki (np. `powiadomienia@example.pl`); DNS bez zmian, w `.env` dane serwera i konta (punkt 4).
Prostsze tam, gdzie polityka organizacji nie pozwala na własny serwer pocztowy.

## 4. Konfiguracja przy starcie (`.env`)

```bash
git clone https://github.com/merkato/sophia-gis.git /opt/sophia && cd /opt/sophia
cp .env.example .env && nano .env
cp config/pg_service.conf.example config/pg_service.conf && nano config/pg_service.conf
chmod 644 config/pg_service.conf
```

**Wymagane:**

| Zmienna | Przykład | Znaczenie |
|---|---|---|
| `SITE_ADDRESS` | `webgis.example.pl` | adres aplikacji (rekord A z punktu 2) |
| `ACME_EMAIL` | `it@example.pl` | kontakt dla Let's Encrypt (wygasające certyfikaty) |
| `POSTGRES_PASSWORD` | długie losowe hasło | hasło bazy — **to samo** w `config/pg_service.conf` |
| `JWT_SECRET` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` | klucz sesji — losowy, tajny |
| `ADMIN_LOGIN`, `ADMIN_PASSWORD` | `admin`, długie hasło | konto administratora tworzone przy pierwszym starcie (zmień hasło po zalogowaniu) |

**Mały serwer albo współdzielony** (limity pamięci): `COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml`.

**Poczta — wariant A** (lekki serwer Sophii):
```ini
COMPOSE_PROFILES=mail
MAIL_DOMAIN=webgis.example.pl
MAIL_HOSTNAME=webgis.example.pl
SMTP_HOST=mail
SMTP_PORT=587
SMTP_FROM=powiadomienia@webgis.example.pl
SMTP_FROM_NAME=Sophia WebGIS
```

**Poczta — wariant B** (konto SMTP organizacji; przykład dla portu 465 z SSL — dla 587 `SMTP_STARTTLS=true`):
```ini
SMTP_HOST=smtp.example.pl
SMTP_PORT=465
SMTP_SSL=true
SMTP_USER=powiadomienia@example.pl
SMTP_PASSWORD=hasło-konta
SMTP_FROM=powiadomienia@example.pl
SMTP_FROM_NAME=Sophia WebGIS
```

Opcjonalnie `PUBLIC_URL=https://webgis.example.pl` — adres w linkach w wiadomościach (domyślnie z `SITE_ADDRESS`),
`RCLONE_REMOTE` — zdalne kopie zapasowe ([SERVER.md](SERVER.md), „Kopie zapasowe”).

## 5. Pierwsze uruchomienie i sprawdzenie

```bash
docker compose up -d --build
docker compose ps                         # wszystkie usługi „Up” (mail — tylko z COMPOSE_PROFILES=mail)
```

1. Otwórz `https://webgis.example.pl` — kłódka w przeglądarce (certyfikat), zaloguj się na `ADMIN_LOGIN`.
2. **Klucz DKIM** (wariant A) — powstaje przy pierwszym starcie kontenera `mail`:
   ```bash
   cat data/mail-dkim/*.txt
   ```
   Treść w nawiasach (`v=DKIM1; k=rsa; p=…`, połączona w jeden ciąg) wpisz jako rekord TXT
   `sophia._domainkey.webgis.example.pl`. Plik klucza prywatnego zostaje na serwerze — nie udostępniaj go.
3. **Wiadomość testowa:** Panel administracyjny → Użytkownicy — wpisz swój adres e-mail w koncie; Panel →
   Wtyczki → (wtyczka z powiadomieniami) → Ustawienia → zaznacz swoje konto → **„Wyślij wiadomość testową”**.
   Sprawdź skrzynkę (także spam) i nagłówki: `spf=pass`, `dkim=pass`, `dmarc=pass`.
4. Problemy z pocztą: `docker compose logs --tail 100 mail` (wariant A) i dziennik wysyłek w API
   (`GET /api/admin/mail/log` — w dokumentacji API `https://webgis.example.pl/api/docs`).

## 6. Po uruchomieniu

- Zmień hasło administratora i załóż konta imienne (Panel → Użytkownicy, grupy, dostęp do projektów).
- Kopie zapasowe: `scripts/server/backup.sh` w cron ([SERVER.md](SERVER.md), „Kopie zapasowe”) — baza, projekty,
  zdjęcia i dokumenty; rastry trzymaj u autora projektów.
- Aktualizacje: `git pull && docker compose up -d --build api web` ([SERVER.md](SERVER.md), „Aktualizacja”).
- Przechowuj poza serwerem: `.env`, `config/pg_service.conf` i (wariant A) `data/mail-dkim/` — bez nich
  odtworzenie po awarii wymaga nowych haseł i nowego klucza DKIM w DNS.
