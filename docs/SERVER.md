# Wdrożenie na VPS (OVHcloud, Ubuntu)

Serwer docelowy: **OVH VPS-2 2026** (6 vCore, 12 GB RAM, 100 GB), świeże Ubuntu 24.04 LTS
(lub 26.04 LTS), profil `docker-compose.small.yml`, adres **webgis.giswgorach.pl**.
Uzasadnienie rozmiaru jest na końcu dokumentu.

Sophia jest główną usługą serwera: jej Caddy zajmuje porty 80/443 i obsługuje certyfikaty także
dla innych subdomen, które powstaną później (patrz [proxy/sites/README.md](../proxy/sites/README.md)).

## 1. Windows: klucz SSH (raz na komputer)

Klient OpenSSH jest wbudowany w Windows 10/11. Skrypt `scripts\windows\setup-ssh.ps1` robi resztę.

```powershell
# a) PowerShell "Uruchom jako administrator" — tylko włączenie usługi ssh-agent
Set-ExecutionPolicy -Scope Process Bypass
D:\dev\sophia\scripts\windows\setup-ssh.ps1 -EnableAgentOnly

# b) Zwykły PowerShell — klucz ed25519, agent, wpis "Host sophia" w ~/.ssh/config
Set-ExecutionPolicy -Scope Process Bypass
D:\dev\sophia\scripts\windows\setup-ssh.ps1 -ConfigureGit
```

* `ssh-keygen` zapyta o **hasło do klucza** — ustaw je. Agent zapamięta je po pierwszym użyciu
  (także po restarcie Windows), więc nie wpisujesz go przy każdym połączeniu.
* Klucz publiczny ląduje w schowku — wklej go w panelu OVH przy zamawianiu VPS (pole „Klucz SSH”).
* `-ConfigureGit` każe Gitowi używać tego samego ssh i agenta (przyda się do GitHub/GitLab).

Po zakupie lub reinstalacji VPS (OVH przyśle IP, domyślny użytkownik to `ubuntu`):

```powershell
D:\dev\sophia\scripts\windows\setup-ssh.ps1 -Server 51.75.12.34
# jeśli VPS zainstalowano BEZ klucza (OVH przysłał hasło):
D:\dev\sophia\scripts\windows\setup-ssh.ps1 -Server 51.75.12.34 -CopyToServer
```

Po **reinstalacji** serwer ma nowy klucz hosta i ssh odmówi połączenia („REMOTE HOST
IDENTIFICATION HAS CHANGED”). Usuń stary wpis: `ssh-keygen -R 51.75.12.34`. Klucz SSH najlepiej
wskazać w panelu OVH już przy reinstalacji.

Od teraz: `ssh sophia`.

## 2. Serwer: pierwsza konfiguracja

```powershell
scp D:\dev\sophia\scripts\server\setup-ubuntu.sh sophia:
ssh sophia "sudo bash setup-ubuntu.sh"
```

Skrypt: aktualizacje, strefa czasowa, swap 2 GB, Docker + rotacja logów, ufw (22/80/443), fail2ban,
automatyczne aktualizacje bezpieczeństwa, katalogi `/opt/sophia` i `/opt/sophia-backups`.
Logowanie hasłem i na roota wyłącza **tylko**, gdy użytkownik ma już klucz — nie odetniesz się.
Po zakończeniu sprawdź w **nowym** oknie `ssh sophia`, zanim zamkniesz poprzednie.

## 3. Aplikacja

```bash
ssh sophia
git clone https://github.com/merkato/sophia-gis.git /opt/sophia
cd /opt/sophia
cp .env.example .env && nano .env          # SITE_ADDRESS=webgis.giswgorach.pl, ACME_EMAIL, hasła, JWT_SECRET
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.small.yml' >> .env
nano config/pg_service.conf                # to samo hasło co POSTGRES_PASSWORD

docker compose up -d --build
docker compose ps
```

Rekord DNS **A** domeny → IP serwera musi istnieć przed startem — Caddy pobierze certyfikat sam.

Inne usługi postawione później na tym serwerze (dashboard, geokoder, …) dopisujesz jako
`proxy/sites/<nazwa>.caddy`. Caddy Sophii wystawi je z certyfikatem, a do kontenerów dotrze przez
wspólną sieć Dockera `edge` (szczegóły w [proxy/sites/README.md](../proxy/sites/README.md)).
Nie uruchamiaj na hoście drugiego proxy (nginx/Apache) na portach 80/443.

## 4. Rastry historyczne

Przygotuj je **lokalnie** (QGIS → OSGeo4W Shell), zanim trafią na serwer:

```bash
# kolorowe skany bez przezroczystości: JPEG w YCbCr, 10–20× mniejsze
gdal_translate -of COG -co COMPRESS=JPEG -co QUALITY=85 -co OVERVIEWS=AUTO skan.tif skan_cog.tif
# czarno-białe / z paletą: bezstratnie
gdal_translate -of COG -co COMPRESS=DEFLATE -co PREDICTOR=2 -co OVERVIEWS=AUTO skan.tif skan_cog.tif
```

**Przezroczystość tylko przez kanał alfa (RGBA), nie przez maskę.** JPEG zamienia alfę na maskę
GDAL, a QGIS maski nie respektuje: wokół obróconego arkusza rysuje czarne kliny. Dla rastrów
z przezroczystym tłem używaj `COMPRESS=WEBP` (stratne, zachowuje alfę, rozmiar jak JPEG), a w QGIS
ustaw w warstwie **Właściwości → Przezroczystość → Pasmo przezroczystości: Pasmo 4**.

**Messtischblatt (TK25): przycięcie do ramki** — `scripts/rasters/messtischblatt.py` liczy ramkę
z numeru arkusza (pierwsze 4 cyfry nazwy pliku) i wycina arkusz z przezroczystością poza nią:

```bat
python scripts\rasters\messtischblatt.py oryginaly\*.tif rastry\ --margin 4
rem gdy georeferencja skanu jest zła: piksele narożników ramki NW NE SW SE w rastrze wejściowym
python scripts\rasters\messtischblatt.py oryginaly\5364_*.tif rastry\ --margin 4 --corners 400,472 3171,461 406,3089 3180,3072
```

`--check` zapisuje samą ramkę jako GeoJSON. Wczytaj ją w QGIS na tle skanu: jeśli nie pokrywa się
z ramką na mapie, georeferencja jest zła i trzeba użyć `--corners`. `--margin 4` (ok. 1 piksel)
usuwa szparę między sąsiednimi arkuszami.

Wiele arkuszy → wtyczka **Fia** → „Zbuduj VRT + piramidy”. Na serwer:

```powershell
scp -r D:\mapy\mapa_1900 sophia:/opt/sophia/data/rasters/
```

W projekcie QGIS ścieżki muszą być **względne**. Fia publikuje projekt do
`data/projects/<slug>/<slug>.qgz`, więc najprościej trzymać rastry w podkatalogu obok projektu
(lokalnie `sokolec\rastry\`, na serwerze `data/projects/sokolec/rastry/`). Ścieżki `./rastry/…`
działają wtedy po obu stronach bez zmian. Kopia zapasowa pomija pliki rastrowe także w tym miejscu.

```powershell
scp -r E:\gis\archiwalne\sokolec\rastry sophia:/opt/sophia/data/projects/sokolec/
```

### Kafle i cache

WebUI pobiera rastry (arkusze, mozaiki, zdalne WMTS) jako kafle WMS 512 px na stałej siatce,
a nginx (`tilecache`, konfiguracja w `proxy/tilecache.conf`) zapisuje je w wolumenie `tiles`
(do 5 GB). Każdy kafel jest renderowany przez QGIS Server tylko raz, a autoryzacja w Caddy działa
nadal dla każdego żądania. Format dobierany jest automatycznie: zdalne WMS/WMTS w JPEG idą jako
JPEG, pozostałe rastry jako 8-bitowy PNG z przezroczystością. Wektory nie są kaflowane ani
cache'owane, bo zmieniają się przy edycji.

Ponowna publikacja projektu z Fii daje automatycznie nowe kafle. **Po podmianie samych plików
rastrowych** (bez publikacji) trzeba zmienić wersję projektu i przeładować QGIS Server:

```bash
cd /opt/sophia
sudo touch data/projects/<slug>/<slug>.qgz && docker compose restart qgis
# albo wyczyść cały cache kafli:
docker compose exec tilecache sh -c 'rm -rf /var/cache/tiles/*'
```

Pliki rastrowe podmieniaj przez wgranie pod tymczasową nazwą i `mv`, nie nadpisuj ich na miejscu:
QGIS Server trzyma je otwarte.

## 5. QGIS Desktop ↔ baza na serwerze

PostGIS nie jest wystawiony do internetu. Łącz się tunelem (wpis `sophia-db` dodał skrypt Windows):

```powershell
ssh -N sophia-db          # zostaw okno otwarte
```

W `pg_service.conf` na Windows: `host=localhost port=15432` w sekcji `[sophia]`.

## 6. Kopie zapasowe

```bash
crontab -e
15 3 * * * /opt/sophia/scripts/server/backup.sh >> /opt/sophia-backups/backup.log 2>&1
```

Codziennie: `pg_dump`, projekty, załączniki PDF, konfiguracja; trzymane 14 dni. Kopia **poza serwerem**:
`sudo apt install rclone`, `rclone config` (OVH Object Storage — S3), w `.env`: `RCLONE_REMOTE=ovh:sophia-backup`.
Rastrów skrypt nie kopiuje — oryginały trzymaj u siebie.

## Rozmiar serwera (VPS-2 2026: 6 vCore, 12 GB)

Profil `docker-compose.small.yml` zabiera Sophii twardo ok. 4,5 GB RAM. Około 7 GB zostaje na inne
usługi i na cache plików rastrów. Gdy inne usługi okażą się lekkie, a rastrów przybędzie, podnieś
w profilu `FCGID_MAX_PROCESSES` do 4 i limit pamięci `qgis` do 3,5 GB.

| Usługa | RAM | Limit w `docker-compose.small.yml` |
|---|---|---|
| PostGIS (ok. 1000 obiektów) | 0,3–0,5 GB | 1 GB |
| QGIS Server (3 procesy, GDAL cache 256 MB) | 1,5–2 GB | 2,5 GB |
| API (2 procesy) | 0,2 GB | 512 MB |
| Caddy + nginx (WebUI, cache kafli) | 0,15 GB | 450 MB |

Reszta RAM to cache plików systemu — z niego korzystają rastry czytane wielokrotnie. Kafle rastrów
są cache'owane na dysku (do 5 GB), więc CPU pracuje głównie przy pierwszym obejrzeniu danego
fragmentu. Kolejny krok przy dużym ruchu to wstępne wygenerowanie kafli (seed), a dopiero potem
większy VPS.
