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
cp config/pg_service.conf.example config/pg_service.conf
nano config/pg_service.conf                # to samo hasło co POSTGRES_PASSWORD (plik poza gitem)

docker compose up -d --build
docker compose ps
```

Rekord DNS **A** domeny → IP serwera musi istnieć przed startem — Caddy pobierze certyfikat sam.

Inne usługi postawione później na tym serwerze (dashboard, geokoder, …) dopisujesz jako
`proxy/sites/<nazwa>.caddy`. Caddy Sophii wystawi je z certyfikatem, a do kontenerów dotrze przez
wspólną sieć Dockera `edge` (szczegóły w [proxy/sites/README.md](../proxy/sites/README.md)).
Nie uruchamiaj na hoście drugiego proxy (nginx/Apache) na portach 80/443.

### Aktualizacja

```bash
cd /opt/sophia && git pull -q && docker compose up -d --build api web
```

**Jednorazowo na instancjach sprzed 12.11.2026** (wtedy `config/pg_service.conf` wyszedł z gita, w repo
jest tylko `pg_service.conf.example`): zmieniony plik z hasłem blokuje `git pull`. Zachowaj go,
pobierz zmiany i przywróć — od tej pory git go nie dotyka:
```bash
cd /opt/sophia && cp config/pg_service.conf /tmp/pg_service.conf.bak \
  && git checkout -- config/pg_service.conf && git pull -q \
  && cp /tmp/pg_service.conf.bak config/pg_service.conf && rm /tmp/pg_service.conf.bak
docker compose up -d --force-recreate api qgis       # pojedynczy plik zamontowany w kontenerach
```

Dwie usługi wymagają dodatkowego kroku, bo `up --build` ich nie restartuje, gdy nie zmienia się
ich konfiguracja w `docker-compose.yml`:

- **zmiana `proxy/Caddyfile`** — odtwórz kontener Caddy (kilka sekund przerwy). `git pull` podmienia
  plik, a kontener z zamontowanym pojedynczym plikiem widzi dalej starą wersję; `caddy reload`
  po cichu wczytałby stary plik:
  ```bash
  docker compose up -d --force-recreate proxy
  docker compose exec proxy cat /etc/caddy/Caddyfile | head      # sprawdź, czy to nowa wersja
  ```
- **zmiana `qgis-server-plugins/`** (np. filtr zakresu danych `sophia_filter`) — zrestartuj QGIS Server:
  ```bash
  docker compose restart qgis
  docker compose logs --tail 50 qgis | grep sophia_filter
  ```

Pliki zmienione w ostatniej aktualizacji pokazuje `git diff --stat HEAD@{1} HEAD`.

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
z numeru arkusza (pierwsze 4 cyfry nazwy pliku; stary numer w nawiasie jest pomijany, `--sheet RRCC`
podaje numer ręcznie) i wycina arkusz z przezroczystością poza nią. Uruchamiaj przez
`messtischblatt.bat`, który ustawia Pythona z GDAL z OSGeo4W/QGIS (systemowy `python` nie ma `osgeo`):

```bat
D:\dev\sophia\scripts\rasters\messtischblatt.bat oryginaly\*.tif E:\gis\rasters\tk25 --margin 4
rem gdy georeferencja skanu jest zła: piksele narożników ramki NW NE SW SE w rastrze wejściowym
D:\dev\sophia\scripts\rasters\messtischblatt.bat oryginaly\5364_*.tif E:\gis\rasters\tk25 --margin 4 --corners 400,472 3171,461 406,3089 3180,3072
```

`--check` zapisuje samą ramkę jako GeoJSON. Wczytaj ją w QGIS na tle skanu: jeśli nie pokrywa się
z ramką na mapie, georeferencja jest zła i trzeba użyć `--corners`. `--margin 4` (ok. 1 piksel)
usuwa szparę między sąsiednimi arkuszami.

Wiele arkuszy → wtyczka **Fia** → „Zbuduj VRT + piramidy”. Na serwer wysyła je
`scripts\windows\sync-rasters.ps1` (opis niżej, „Wysyłanie rastrów”).

W projekcie QGIS ścieżki muszą być **względne**. Fia publikuje projekt do
`data/projects/<slug>/<slug>.qgz`, więc najprościej trzymać rastry w podkatalogu obok projektu
(lokalnie `moj-projekt\rastry\`, na serwerze `data/projects/moj-projekt/rastry/`). Ścieżki `./rastry/…`
działają wtedy po obu stronach bez zmian. Kopia zapasowa pomija pliki rastrowe także w tym miejscu.

### Wysyłanie rastrów (`sync-rasters.ps1`)

Jedno polecenie z Windows (PowerShell, w katalogu repozytorium) wysyła folder z rastrami we właściwe
miejsce na serwerze:

```powershell
.\scripts\windows\sync-rasters.ps1 -Source E:\gis\projekty\moj-projekt\rastry\mapa_1900 -DryRun
.\scripts\windows\sync-rasters.ps1 -Source E:\gis\projekty\moj-projekt\rastry\mapa_1900
.\scripts\windows\sync-rasters.ps1 -Source E:\gis\rasters\tk25
```

- **Cel wynika z folderu**: folder w `E:\gis\rasters\<seria>` → biblioteka `data/rasters/<seria>`;
  folder w projekcie → `data/projects/<slug>/<ta sama ścieżka względna>` (projekt = najbliższy folder
  nadrzędny z plikiem `.qgz`; slug = nazwa pliku `.qgz` albo `-Project <slug>`). Projekt musi być
  wcześniej opublikowany przez Fię.
- Wysyła tylko pliki **nowe i zmienione** (`.tif`, `.vrt`, `.ovr`, `.jp2` — porównanie MD5); każdy plik
  trafia najpierw pod nazwą tymczasową, więc QGIS Server nie czyta niedokończonego pliku.
- Na koniec **restartuje QGIS Server** (trzyma otwarte rastry i pamięta warstwy, których brakowało),
  a gdy coś podmieniono lub usunięto — **czyści cache kafli**.
- `-DryRun` — tylko plan; `-Delete` — usuwa na serwerze pliki, których nie ma lokalnie (bez tej
  opcji są tylko wypisane); `-NoRestart` — bez restartu.
- Katalog projektu na serwerze należy do roota (tworzy go API przy publikacji) — skrypt przygotowuje
  podkatalog przez kontener `api`, bez `sudo`.

### Biblioteka rastrów dla wielu projektów

Serie używane w kilku projektach (np. TK25) trzymaj w jednym miejscu, jako jeden VRT:

```
E:\gis\rasters\tk25\  (arkusze .tif, tk25.vrt, tk25.vrt.ovr)  ->  /opt/sophia/data/rasters/tk25/
E:\gis\<folder>\<projekt>\<projekt>.qgz                       ->  /opt/sophia/data/projects/<slug>/<slug>.qgz
```

Projekt musi leżeć dwa poziomy pod `E:\gis`. Wtedy ścieżka względna `../../rasters/tk25/tk25.vrt`
działa lokalnie i na serwerze (w kontenerze `/projects/<slug>/../../rasters` = `/rasters`).
W QGIS warstwa VRT potrzebuje pasma 4 jako pasma przezroczystości.

Po dodaniu arkusza (w OSGeo4W Shell, w `E:\gis\rasters\tk25`):

```bat
dir /b *.tif > lista.txt && gdalbuildvrt -resolution highest -r average -input_file_list lista.txt tk25.vrt && del lista.txt
del tk25.vrt.ovr
gdaladdo -r average --config COMPRESS_OVERVIEW WEBP --config WEBP_LEVEL_OVERVIEW 85 --config SPARSE_OK_OVERVIEW YES --config GDAL_TIFF_OVR_BLOCKSIZE 512 tk25.vrt 2 4 8 16 32 64 128 256
```

**Piramidy VRT (`tk25.vrt.ovr`) są obowiązkowe.** Arkusze mają różne rozdzielczości, więc GDAL nie
użyje piramid samych arkuszy i bez `.ovr` oddalony widok czyta pełną rozdzielczość: 150 s zamiast
0,3 s na jeden obraz. Potem `sync-rasters.ps1 -Source E:\gis\rasters\tk25` — wyśle nowe arkusze,
`tk25.vrt` i `tk25.vrt.ovr`, zrestartuje `qgis` i wyczyści cache kafli.

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

PostGIS nie jest wystawiony do internetu. Łączysz się tunelem SSH (wpis `sophia-db` dodał
`setup-ssh.ps1`): `localhost:15432` na Windows → `127.0.0.1:5432` na serwerze.

```powershell
D:\dev\sophia\scripts\windows\setup-pg.ps1 -StartTunnel
```

Skrypt:
* zapisuje usługę `[sophia]` w `%APPDATA%\postgresql\.pg_service.conf`, **bez hasła**;
* pyta o hasło (`POSTGRES_PASSWORD` z `/opt/sophia/.env`) i zapisuje je w `%APPDATA%\postgresql\pgpass.conf`
  z dostępem tylko dla Ciebie;
* uruchamia tunel w tle i testuje połączenie.

Tunel na stałe, także po restarcie Windows:

```powershell
D:\dev\sophia\scripts\windows\setup-pg.ps1 -SkipPassword -Autostart
```

Rejestruje zadanie Harmonogramu „Sophia tunel bazy (sophia-db)”, które po zalogowaniu uruchamia
`scripts\windows\sophia-tunnel.ps1` w tle. Pętla wznawia tunel po zerwaniu (uśpienie, zmiana sieci).
Wymaga klucza SSH bez hasła albo działającego ssh-agent. Usunięcie: `-RemoveAutostart`.
Zadanie wskazuje skrypt w repo, więc po przeniesieniu repo trzeba uruchomić `-Autostart` ponownie.

**W QGIS:** Przeglądarka → PostgreSQL → *Nowe połączenie* → Nazwa `sophia`, **Usługa** `sophia`,
pozostałe pola (host, port, baza, uwierzytelnianie) **puste**. Dzięki temu źródło warstw
w projekcie to samo `service='sophia' … table=…`. Na serwerze ta sama nazwa usługi wskazuje
kontener `db`, więc projekt działa po publikacji bez żadnych zmian. Nie zapisuj w połączeniu
loginu ani hasła: trafiłyby do projektu, a diagnostyka Fii zgłosi taką warstwę.

## 5b. Osierocone pliki zdjęć i dokumentów

Zdjęcie usunięte z pola albo rekord zdjęcia/dokumentu usunięty w WebUI zostawia plik w
`data/uploads/<projekt>/`. Sprzątanie jest w panelu administratora (zakładka **Pliki**) albo z konsoli:

```bash
docker compose exec api python -m app.uploads              # raport (nic nie zmienia)
docker compose exec api python -m app.uploads --apply      # sieroty starsze niż 7 dni -> kosz projektu
docker compose exec api python -m app.uploads --purge 30   # usuń z koszy wpisy starsze niż 30 dni
```

- Osierocony = brak odwołania w jakimkolwiek rekordzie warstw projektu (wszystkie rekordy, bez filtrów).
- Pliki młodsze niż 7 dni (`--min-age`) zostają — mogą czekać na zapis formularza.
- Pliki trafiają do `data/uploads/<projekt>/.kosz/<data>/…` z zachowaniem ścieżki; odzyskanie =
  przeniesienie z powrotem. Kopia zapasowa pomija kosz.
- Gdy którejś warstwy nie da się odczytać (np. baza niedostępna), projekt jest pomijany.

Automatycznie, np. co tydzień (cron użytkownika z dostępem do Dockera):

```bash
0 4 * * 0  cd /opt/sophia && docker compose exec -T api python -m app.uploads --apply --purge 30 >> /var/log/sophia-uploads.log 2>&1
```

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
