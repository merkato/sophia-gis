# TO DO — Sophia (WebUI, API, Fia)

Aktualizacja 25.11.2026 (wdrożona Sophia 0.9.2). Na górze plan (kolejność = kolejność realizacji), niżej zrobione — tematycznie.
Tylko rdzeń Sophii i ogólne wtyczki z `sophia-plugins`; prace wtyczek branżowych (np. wyłączenia) — w ich repozytoriach.

Oznaczenia: ✅ zrobione · ✔️ zrobione częściowo (co zostało — w planie) · ⬜ do zrobienia

---

## Plan

### ⬜ 1. Do przetestowania (zrobione, nieprzetestowane w pełni)
- ⬜ Narzędzia edycji geometrii w przeglądarce na prawdziwych danych, cofanie (Ctrl+Z).

### ⬜ 2. Drobne zaległości
- ⬜ Kolejne źródła narzędzi pobierania: PRG adresy, BDOT10k (nowy wpis w `SOURCES` i w `fia/tools.py`).
- ✅ Przyciąganie i kontrola topologii w edycji — **od początku, na każdej warstwie edycyjnej** (ustalenia 23.11;
  przetestowane 23.11: wierzchołki, pierścień, przyciąganie do wierzchołków i krawędzi innej warstwy, blokada nakładania):
  - przyciąganie do węzłów (i krawędzi) istniejących geometrii: warstwy edycyjnej i wskazanych warstw odniesienia
    (np. kontur → działki, użytki, inne kontury; użytek → działki, inne użytki; działka z dnia decyzji → działki);
    zestaw warstw i tolerancja z ustawień przyciągania projektu QGIS, przełącznik w aplikacji;
  - kontrola topologii przy zapisie (nakładanie z innymi obiektami warstwy, wyjście poza obiekt nadrzędny
    w tolerancji) — komunikat z miejscem błędu na mapie;
  - usuwanie wierzchołków wygodniej niż Alt+klik (np. zaznaczenie + Delete);
  - nakładka działek z powiatów (KIEG, WMS) jako warstwa odniesienia — podgląd; przyciąganie tylko do danych
    wektorowych (rejestr EGiB / ULDK w bazie).
  - **Plan realizacji (0.9.0, 23.11 — etapy 1–5 ✔️ zrobione, do testu po wdrożeniu):**
    1. API: ustawienia przyciągania z projektu QGIS (`<snapping-settings>`: włączone, tryb, tolerancja i jednostka,
       warstwy w trybie zaawansowanym; „unikaj nakładania” — `avoidIntersectionsLayers`) → `config.snapping`.
    2. Mapa: warstwy odniesienia — obiekty wskazanych warstw z bieżącego widoku (API features, limit) w niewidocznym
       źródle; `Snap` na warstwie edycyjnej i odniesienia; tolerancja w pikselach.
    3. Pasek narzędzi: przełącznik przyciągania (wł./wył., zapamiętany) i lista warstw odniesienia.
    4. Kontrola topologii przy zapisie (API): nakładanie na inne obiekty warstwy z listy „unikaj nakładania”
       (> tolerancja) — błąd z geometrią miejsca, mapa pokazuje je na czerwono (warstwa porównania „uwaga”).
    5. Usuwanie wierzchołka: kliknięcie wierzchołka w trybie zmiany wierzchołków + Delete (obok Alt+klik).

### ✔️ 3. Wysyłka rastrów z Fii (TIFF, OVR, VRT) — plan z 25.11 (Sophia 0.10.0, Fia 0.2.0 — etapy 1–7 ✔️, do testu)
Pełny ciąg od warstw rastrowych projektu QGIS do serwera, w Fii i API — bez `sync-rasters.ps1` i bez poleceń
na serwerze. Fia: Python + GDAL z QGIS; API: nowy router. Skrypt PowerShell zostaje jako zapas.

**Test na serwerze (25.11, projekt testowy, posprzątane):** QGIS Server trzyma otwarte rastry — podmiana pliku
(zapis pod nazwą tymczasową + `rename`) bez zmiany projektu daje stary obraz; po zmianie czasu modyfikacji
pliku projektu (`touch`) wszystkie procesy od razu pokazują nowy obraz. Sprawdzone: pojedynczy TIFF, mozaika VRT
z podmienionymi arkuszami, piramidy `.vrt.ovr` (widok oddalony), plik dodany po wczytaniu projektu (wcześniej
błąd 500 — po `touch` warstwa działa), raster biblioteki `/rasters` (poza katalogiem projektu), kilka procesów
naraz. **Restart `qgis` nie jest potrzebny** (wystarczy `touch` projektu). Adresy kafli zawierają wersję
projektu (= czas modyfikacji `.qgz`), więc cache kafli nie wymaga czyszczenia — poza podkładami typu „sophia”
(wersja z `updated_at` podkładu).

**Stan na serwerze (sprawdzone 25.11):** API działa jako root → pliki 644 czytelne dla `www-data` (QGIS Server);
`data/rasters` (właściciel ubuntu) — API ma zapis po zamontowaniu; wolne 67 GB z 96 GB; Caddy: `max_size 100MB`
na `/api/*`; kopia zapasowa pomija `*.tif/.ovr/.vrt/.aux.xml` (bez zmian); w obrazie API brak GDAL — walidacja
plików bez GDAL (nagłówek TIFF, XML VRT).
**Stan lokalnie:** VRT z Fii mają ścieżki względne (`relativeToVRT="1"`); w folderach `rastry/` leżą też pliki
nieużywane (geojson, py, VRT robocze — np. 15 VRT, z których projekt używa 4) → wysyłamy **pliki warstw**
(`GetFileList()`), nie cały folder. Fia: QGIS 3.40–4.x, wzorzec postępu jak „Pobierz zdjęcia” (`photosync.py`).

#### Etapy
1. ✔️ **Serwer (docker-compose):** w `api` zamontować `./data/rasters:/rasters` z zapisem (`qgis` bez zmian — ro);
   `RASTERS_DIR` w ustawieniach API. Wdrożenie: `docker compose up -d api`.
2. ✔️ **API `routers/rasters.py`** (`/api/admin/rasters`), uprawnienia: rastry projektu — administrator albo
   właściciel projektu (jak publikacja); biblioteka `data/rasters/<seria>` — tylko administrator.
   - `POST /plan` `{target: {project: slug} | {library: seria}, files: [{path, size, sha256}]}` →
     `{upload: [...], same: [...], extra: [...], free_bytes, session}`; projekt musi być opublikowany;
     odmowa, gdy brak miejsca (rozmiar + 10%).
   - `PUT /sessions/{id}/files/{path}?offset=` — części po 32 MB do `<cel>/.upload-<id>/<path>.part`
     (poniżej limitu Caddy); `GET /sessions/{id}` — ile odebrano (wznawianie po przerwie).
   - `POST /sessions/{id}/commit` `{delete_extra: bool}` — kontrola SHA-256, walidacja, `rename` w kolejności
     arkusze → `.ovr` → `.vrt`, usuwanie nadmiaru tylko na żądanie; potem `touch` projektu (biblioteka: wszystkich
     projektów, które jej używają — źródła warstw z `.qgz`) i `updated_at = now()` podkładów „sophia” z tych
     projektów; wpis w dzienniku zmian; usunięcie katalogu sesji. `DELETE /sessions/{id}` — przerwanie.
   - Walidacja: rozszerzenia `.tif .tiff .vrt .ovr .aux.xml` (opcjonalnie `.tfw`); ścieżka względna bez `..`,
     bez `\`, NFC; nagłówek TIFF/BigTIFF (`II*\0`, `MM\0*`, `II+\0`); **VRT:** poprawny XML, każde
     `SourceFilename` z `relativeToVRT="1"`, wskazuje plik wewnątrz katalogu docelowego (po wysyłce albo już
     na serwerze), bez `/vsi…`, bez `PixelFunctionLanguage`/`PixelFunctionCode` (Python) — spreparowany VRT
     mógłby przez WMS czytać dowolne pliki serwera albo pobierać z sieci.
   - Sprzątanie sesji starszych niż 24 h (przy każdym `plan`). Testy: walidacja VRT i ścieżek, plan
     (nowe/zmienione/nadmiar), wznawianie, commit z `touch`.
3. ✔️ **Fia — spis i kontrola** (`fia/rasterupload.py`, zakładka „Wysyłka rastrów” — `fia/raster_upload_tab.py`):
   - warstwy GDAL z plikiem: `gdal.Open(źródło).GetFileList()` (VRT → arkusze; `.ovr`, `.aux.xml`); miejsce
     na serwerze z reguły `checks._raster_location` (obok projektu → `data/projects/<slug>/…`,
     `../../rasters/<seria>` → biblioteka); raster poza oboma — błąd z podpowiedzią;
   - kontrole: ścieżka względna w projekcie (ustawienie „Zapisz ścieżki: względne”), źródła VRT względne,
     **zgodność wielkości liter** nazw w VRT z plikami na dysku (Linux), brak piramid (VRT — błąd; duży TIFF —
     ostrzeżenie), raster bez kompresji (informacja), znaki w nazwach (spacje i polskie litery są dozwolone);
   - tabela: warstwa · pliki (liczba, rozmiar) · miejsce na serwerze · stan (nowe / zmienione / aktualne —
     po „Sprawdź na serwerze”) · uwagi.
4. ✔️ **Fia — wysyłka:** „Sprawdź na serwerze” (SHA-256 lokalnie, z pamięcią sum w `.fia-hash.json` po
   rozmiarze i czasie modyfikacji — 2 GB nie liczymy za każdym razem) → podsumowanie (do wysłania N plików / X MB,
   nadmiar na serwerze) → „Wyślij” z postępem (plik, MB/s, pozostały czas), przerwaniem i wznawianiem; nadmiar —
   pytanie o usunięcie (domyślnie nie). Komunikacja przez `urllib` jak `publish.py` (token, weryfikacja SSL).
5. ✔️ **Fia — przygotowanie** („Przygotuj…” przy warstwie z problemem): przepisanie źródeł VRT na względne,
   poprawa wielkości liter, kopia rastra spoza projektu do `rastry/<nazwa>/` z przepięciem źródła warstwy,
   budowa brakujących piramid (`overview_settings` jak w „Zbuduj VRT + piramidy”). Konwersja TIFF do COG — później.
6. ✔️ **Publikacja:** w zakładce „Serwer” pole „Po publikacji wyślij zmienione rastry” — najpierw `.qgz`
   (działa też przy pierwszej publikacji; dotychczasowe rastry działają do podmiany), potem rastry; zatwierdzenie
   wysyłki odświeża projekt. Notka o `data/rasters` w zakładce zmieniona; token zapamiętany na czas pracy okna.
7. ✔️ **Dokumentacja i wersje:** `docs/SERVER.md` (rastry: Fia jako główna droga, `sync-rasters.ps1` jako
   zapas), `docs/user`/Fia, `docs/ARCHITECTURE.md` (punkt „biblioteka rastrów + narzędzie wysyłki” — odhaczyć); Sophia 0.10.0, Fia 0.2.0.
8. ⬜ **Test końcowy:** wysyłka nowej serii do projektu testowego, podmiana arkusza i piramid, wznowienie po
   przerwanym połączeniu, odmowa VRT ze ścieżką bezwzględną, biblioteka (tylko administrator), widok w WebUI
   bez restartu `qgis`.

**Zrobione 25.11:** testy API (walidacja ścieżek i VRT, nadmiar, pamięć sum, sesje, zatwierdzenie z odświeżeniem
projektów, biblioteka), logika Fii w PyQGIS (spis, kontrola, poprawa VRT — także odporna na nadpisanie przez
otwarty VRT, piramidy, kopia do projektu) i ciąg end-to-end klient Fii ↔ API (przerwanie i wznowienie, korekta
przesunięcia, odmowa niedokończonej sesji, zmiana i usunięcie arkusza, odmowa VRT z `/etc/passwd`).
Do zrobienia: etap 8 na serwerze po wdrożeniu (wymaga montowania `data/rasters` w `api`) i test okna Fii w QGIS.

#### Ustalenia (25.11, przyjęte propozycje)
- Biblioteka `data/rasters` z Fii: tylko administrator.
- „Przygotuj” poprawia VRT w miejscu (kopia `.bak`), piramidy obok (`.ovr`); COG — jako nowy plik (później).
- Nadmiar na serwerze: pytanie przy wysyłce, domyślnie nie usuwać.
- Konwersja do COG: później (poza tym zakresem).

### ✔️ Obiekty chronione i bezpiecznik (25.11, Sophia 0.10.0, egib 1.6.0 — do testu)
- ✔️ Manifest wtyczki `protected` (tabela, pole, wartości, komunikat) — `app/protection.py`; obiekt w API z `protected`,
  WebUI: formularz tylko do odczytu (🔒), obiekty poza warstwą edycyjną (narzędzia ich nie chwytają), bez usuwania.
- ✔️ Kontrola w API przy każdym zapisie istniejącego obiektu (`in_scope` → `check_protected`).
- ✔️ Bezpiecznik: Panel → Projekty → „Odblokuj obiekty chronione…” (powód, 1–24 h; `portal.protection_unlock`,
  dziennik `protection_unlock_log`); zmieniać mogą administrator i zarządzający; `sophia.odblokowanie = 'on'`
  w transakcji dla wyzwalaczy wtyczki. egib 1.6.0 (migracja 007): działki i użytki z GML chronione; przy
  odblokowaniu zmiana bieżącego wiersza rejestru (geometria, powierzchnia, OFU), usunięcie — zawsze tylko importem.
  Sprawdzone na bazie w transakcji wycofanej (odmowa / zapis przy odblokowaniu / odmowa usunięcia).

### ✔️ Formularze i pasek narzędzi — uwagi z testów (25.11, Sophia 0.10.0, do testu)
- ✔️ Nowy obiekt: „Anuluj” w formularzu (bez pytania); okno „Niezapisane zmiany” zawsze na wierzchu; formularz nad oknami
  wtyczek po otwarciu i kliknięciu (wspólny licznik warstw okien).
- ✔️ Komunikat o brakach przy „Zapisz” (pod przyciskiem, z przewinięciem) i obramowanie pól do uzupełnienia;
  zakres widżetu „Zakres” z projektu (Min / Max) sprawdzany przed zapisem; naruszony warunek CHECK w bazie —
  „niedozwolona wartość (warunek …)”.
- ✔️ Nowy obiekt bez pól tylko do odczytu, które i tak są puste (np. data utworzenia).
- ✔️ „+ Dodaj obiekt” (rysowanie) / „+ Dodaj rekord” w tabeli atrybutów każdej warstwy z prawem dodawania;
  „+ Dodaj” rekordu podrzędnego tylko w formularzu warstwy edytowalnej (nie z warstw referencyjnych).
- ✔️ Pasek: narzędzia edycji dopiero po wybraniu warstwy edycyjnej i tylko te, na które pozwalają prawa i typ geometrii.
- ✔️ Zakładki formularza wyglądają jak zakładki (nie jak linki); sama „Atrybuty” — bez paska zakładek.
- ✔️ `host.onFeatureChange` — wtyczki dostają zapis / usunięcie obiektu (odświeżenie okien).

### ⬜ 4. Graficzny edytor schematu bazy (WebUI) — plan z 15.11
Diagram tabel jak w narzędziach ERD: karty tabel przeciągane po płótnie, relacja = „sznurek”
przeciągnięty z pola na pole. Działa na istniejących schematach danych (dziś `dane`, `rdlp`,
`straznicy`) i na nowych. Panel administratora → **Baza danych**.

**Zasady**
- Schematy danych z bazy Sophii, bez `portal`, `public` i schematów systemowych (lista wykluczeń
  w konfiguracji API). Nazwy tabel i pól: małe litery, cyfry, `_` (bez polskich znaków — QGIS, SQL,
  eksporty); polska nazwa jako **komentarz** kolumny/tabeli, który Fia przenosi na alias w QGIS.
- Zmiany rysuje się na płótnie jako szkic, potem **„Podgląd zmian”** pokazuje SQL, a **„Zastosuj”**
  wykonuje wszystko w jednej transakcji. Każda zmiana schematu trafia do dziennika (kto, kiedy, SQL).
- Operacje niszczące (usuń tabelę/pole, zmiana typu z danymi) — osobne potwierdzenie z liczbą wierszy
  i listą projektów, które używają tabeli/pola (z opublikowanych projektów QGIS). Kopia nocna jest.
- Uprawnienia: **tylko administrator** (decyzja 15.11) — API sprawdza `is_admin` przy każdej zmianie,
  pozostali nie widzą zakładki.

**Model w edytorze**
- **Tabela**: nazwa, komentarz, rodzaj — *atrybutowa* albo *geometryczna* (punkt / linia / poligon,
  „wieloczęściowa”, układ — domyślnie EPSG:2180). Klucz główny `fid` (identity) i indeks przestrzenny
  zakładane same.
- **Pole**: nazwa, typ z prostej listy (tekst, liczba całkowita, liczba dziesiętna, data, data i czas,
  tak/nie, uuid), wymagane, wartość domyślna, unikalne, komentarz. Szablony pól: „data utworzenia”
  (`now()`), „autor”.
- **Relacja** (sznurek z pola tabeli podrzędnej na klucz tabeli nadrzędnej; upuszczenie na nagłówek
  tabeli zakłada nowe pole `<tabela>_fid`): klucz obcy z indeksem; *Kompozycja* (usuń z rodzicem,
  `ON DELETE CASCADE`) albo *Powiązanie* (`SET NULL` / `RESTRICT`). Kontrola zgodności typów.
- **Słownik**: gotowy szablon tabeli `kod` + `opis` z wartościami wpisanymi od razu; pole podpięte
  sznurkiem do słownika → w QGIS lista wartości (ValueRelation).

**Etapy**
1. ⬜ **Odczyt**: API odczytuje schemat z katalogu bazy (tabele, kolumny, klucze, relacje, geometrie,
   komentarze, liczba wierszy, użycie w projektach); diagram tylko do oglądania, układ kart zapamiętany
   w bazie (`portal`, per schemat). Biblioteka diagramu: React Flow (`@xyflow/react`, MIT) — uchwyty na
   poziomie wierszy pól dają „sznurki z pola na pole”.
2. ⬜ **Tworzenie**: nowy schemat, nowa tabela (atrybutowa / geometryczna), nowe pola; podgląd SQL,
   zastosowanie w transakcji, dziennik zmian (migracja w `portal`).
3. ⬜ **Relacje i słowniki**: sznurki, okno relacji, usuwanie relacji, słownik z wartościami.
4. ⬜ **Zmiany i usuwanie**: zmiana nazwy, typu (z `USING`), usuwanie pól i tabel — z potwierdzeniami
   i ostrzeżeniem o projektach, które przestaną działać.
5. ⬜ **Fia**: „Dodaj warstwy z bazy Sophii” — warstwy przez `service=sophia`, relacje QGIS z kluczy
   obcych (Sophia czyta relacje z projektu, nie z bazy), ValueRelation dla słowników, aliasy
   z komentarzy, pola wymagane; Diagnostyka ostrzega o kluczu obcym bez relacji w projekcie.
6. ⬜ Testy (generator SQL — jednostkowe; próba na tymczasowym schemacie na serwerze), dokumentacja
   `docs/user/baza.md`. Na telefonie diagram tylko do podglądu.

---

## Zrobione

### ✅ Formularz i tabela atrybutów
- ✅ Formularz obiektu jako okno nad mapą: przesuwane, zmiana rozmiaru, zwijanie; na telefonie pełny ekran
  (a048d5b).
- ✅ Po zapisie kliknięcie innego obiektu wczytuje go do formularza; przy niezapisanych zmianach pytanie
  zapisz / odrzuć / anuluj (1a90dd1).
- ✅ Tabela atrybutów zamiast listy rekordów: okno nad mapą, sortowanie i wyszukiwanie po stronie API,
  ukrywanie kolumn, stronicowanie, wiersz → formularz i przybliżenie (`AttributeTable.tsx`,
  `FloatingWindow.tsx`).

- ✅ Układ formularza z projektanta QGIS (przeciągnij i upuść): kolejność pól, pola spoza układu ukryte;
  krótkie pola obok siebie (typ i średnia szerokość z bazy, wiersze po 6 kolumn), znaczniki czasu tylko do
  odczytu w czasie lokalnym (0.4–0.5).
- ✅ Rekordy powiązane: tabela podrzędna jest galerią zdjęć/dokumentów tylko przy ≤ 3 widocznych polach
  poza kluczami i załącznikiem — inaczej zwykła lista (np. lustracje).

### ✅ Zdjęcia, dokumenty i pliki
- ✅ Zdjęcia, także z aparatu telefonu: pole „Załącznik” (wariant A) albo tabela zdjęć w relacji
  (wariant B), HEIC → JPEG, miniatury, EXIF, galeria, pobieranie do QGIS przez Fię (08a7116,
  `docs/user/zdjecia.md`).
- ✅ Dokumenty (PDF, GML, DOCX…) tak samo jak zdjęcia, pliki bez zmian w `data/uploads/<slug>/pliki`
  (`docs/user/zalaczniki.md`).
- ✅ Sprzątanie plików osieroconych: kosz projektu, próg 7 dni, panel → Pliki, `python -m app.uploads`
  (`docs/SERVER.md`, 5b).
- ✅ Limity wielkości plików per zbiór (pole „Załącznik”, zbiory wtyczek — `upload_sets`): Fia → Pliki (przenoszone
  na serwer przy publikacji), panel → Projekty → „Przechowywanie plików…”; tylko niższe od globalnych
  (`app/storage.py`, `portal.upload_limits`) (22.11).

### ✅ Pasek narzędzi
- ✅ Górny pasek narzędzi edycji, wyszarzony bez warstwy edycyjnej; wybór warstwy z drzewa i z listy.
- ✅ Ikony w stylu QGIS z podpowiedziami — własne SVG (`Icons.tsx`), bez grafik QGIS (GPL).
- ✅ Pomiar długości oraz powierzchni z obwodem (`web/src/measure.ts`): etykiety przy szkicu, płasko w układzie
  projektu (metrycznym), przyciąganie do warstwy edycyjnej, Esc / Backspace / Delete; działa też bez projektu (22.11).
  Przetestowane 22.11 w przeglądarce.
- ✅ Etykieta powierzchni i obwodu (długości) przy rysowaniu i zmianie wierzchołków obiektów warstwy edycyjnej (0.8.3).
- ✅ Obraz z pliku z wtyczki (0.8.5): `host.showOnMap({ raster, edit })` — obraz (np. GeoTIFF przetworzony przez wtyczkę)
  nad podkładami z przybliżeniem do zasięgu, „Obraz z pliku” w panelu warstw; warstwa z tabeli widoczna i w edycji
  z polami nowych obiektów. Ramka „Usługi zewnętrzne” wokół podkładów i nakładek (0.8.4).
- ✔️ Porównanie geometrii z wtyczki (0.8.6): `host.showOnMap({ compare })` — geometrie historyczne (szare, przerywane)
  i aktualne (pomarańczowe) z podpisami na osobnej warstwie, „Porównanie geometrii” w panelu warstw z legendą;
  łączy się z rysowaniem / edycją (np. działka z dnia decyzji na tle działek aktualnych).

### ✅ Edycja geometrii
Szkic w przeglądarce z przyciąganiem, geometrię liczy PostGIS w API: jedna transakcja, kontrola zakresu
danych, wpis do dziennika zmian. Opis: `docs/user/README.md`.
- ✅ Podział obiektów (polityki podziału pól z projektu QGIS), Esc/Backspace w szkicach (12.11).
- ✅ Pierścień, pierścień wypełniony, usuń pierścień, usuń część, połącz obiekty (zdjęcia i rekordy
  powiązane przechodzą do obiektu, który zostaje), przesuń obiekt (14.11).
- ✅ Dodaj część, przekształć (poligony i linie), obróć, kopiuj (polityki duplikowania) (15.11, 70af12f).
- ✅ Cofnij ostatnią operację z dziennika zmian, Ctrl+Z; odmowa, gdy obiekt zmieniono później
  (migracja `audit_undo`).

### ✅ Uprawnienia i zakres danych
- ✅ Przetestowane w praktyce (wyłączenia, 22.11): zakładka Fii „Zakres danych”, zapamiętane poświadczenia Fii,
  narzędzie pobierania ULDK zdefiniowane w Fii działa w aplikacji.
- ✅ Serwer → projekt → zakres danych: autor projektów, role w grupach, prawa do zdjęć i plików, zakres
  przestrzenny / atrybut / przez relację / bez filtra (`api/app/scope.py`).
- ✅ Jeden filtr w API i w QGIS Server (wtyczka `sophia_filter`), Fia: zakładka „Zakres danych”,
  `docs/user/uprawnienia.md`. Stare zasięgi wycofane.

### ✅ Narzędzia pobierania
- ✅ ULDK: działka i budynek z kliknięcia do warstwy projektu, mapowanie pól w Fii, karta wyniku
  (`api/app/fetchers.py`, `fia/tools.py`, `docs/user/uldk.md`). Kolejne źródła → plan, punkt 2.

### ✅ Mapa, warstwy i podkłady
- ✅ Mapa z podkładami także bez projektu i dla niezalogowanych; na liście projektów pozycja
  „bez projektu (same podkłady)” (15.11 — wcześniej tryb był dostępny tylko bez żadnego projektu).
  Sprawdzone w przeglądarce jako gość: mapa całej Polski i wydruk A4 z ortofotomapą i źródłem GUGiK.
- ✅ Panel warstw: podkład i nakładki na dole, przezroczystość ◐ dla rastrów, podkładów i nakładek
  (af0ccb6).
- ✅ Atrybucja warstw z projektu QGIS na mapie i w „Źródłach” wydruku (56a4ef9).
- ✅ Rastry: `sync-rasters.ps1` (wysyłka zmienionych plików, restart QGIS Server, czyszczenie cache kafli),
  Fia: VRT z piramidami, także RGBA (11.11).

### ✅ Raporty i PDF
- ✅ `app.pdf.html_to_pdf` — dokumenty z HTML/CSS jako **PDF/A-2b** (WeasyPrint, czcionki DejaVu i Liberation
  osadzone, zasoby tylko jako `data:`), gotowe do podpisu elektronicznego; nagłówki, stopki, „Strona X z Y”.
- ✅ Raporty do PDF z filtrem zakresu użytkownika budują wtyczki na tym mechanizmie (np. załączniki
  sprawozdawcze, także paczka ZIP wielu PDF) — zamiast raportów z menedżera wydruków QGIS.

### ✅ Wydruki
- ✅ Układ Sophii w przeglądarce: bieżący widok z podkładami i warstwami na A4/A3, tytuł, skala,
  podziałka, data, źródła (`web/src/print.ts`).
- ✅ Szablony QGIS z panelu „Wydruk”: stałe skale, ramka na mapie, tytuł/opis do etykiet `tytul`/`opis`,
  podkład z warstwy projektu tej samej usługi; GetPrint w WMS 1.1.1, kolejność warstw
  (`docs/user/wydruki.md`).
- ✅ Ramka mapy szablonu zachowuje proporcje z szablonu (`fit_extent`, a77be9a). Wydruk z panelu
  sprawdzony w przeglądarce 15.11 (gość, projekt kolejowy, 1:50 000 — zgodny z ramką na mapie).
- ✅ Etykiety `zrodla` (atrybucje) i `autor` (zalogowany użytkownik), przezroczystość ◐ w szablonie
  (`OPACITIES` w GetPrint), panel podaje, co wpisze do szablonu (15.11, 6c84653). Krycie z panelu
  dociera do QGIS Server (sprawdzone w przeglądarce).
  Przetestowane 22.11 na szablonie z ramkami tekstowymi `zrodla` i `autor`.
- ✅ Układ Sophii przy dużych rastrach: licznik postępu kafli, najwyżej 6 zapytań naraz, limit od
  ostatniego postępu (45 s) zamiast stałych 60 s, najwyżej 5 min; w karcie w tle limit stoi (15.11,
  cfde0c1). Sprawdzone w przeglądarce: Schmettau A3, 200 dpi, 1:25 000 — 98 kafli w 5 s, z licznikiem.
- ✅ Dokumentacja `docs/user/wydruki.md`: etykiety, legenda, mapa przeglądowa, postęp i limity.
- ✅ Obrót mapy szablonu (`map0:ROTATION`, pole „Obrót mapy”, obrócona ramka na mapie); sprawdzone GetPrint
  na serwerze — treść obraca się zgodnie z zegarem, ramka w przeciwną stronę (22.11).
- ✅ Podkłady z katalogu w szablonie: Fia → Raporty → „Dodaj podkłady Sophii do projektu…” (WMTS, WMS, XYZ jako
  „Tylko w QGIS”, grupa „Podkłady Sophii”); API dopasowuje także podkłady WMS. Fia → Diagnostyka: brak szablonów
  (informacja), mapy szablonów z warstwami, których Sophia nie wydrukuje (ostrzeżenie). Wydruk bez szablonu —
  układ Sophii (22.11).
  Przetestowane 22.11 w QGIS.

### ✅ Wtyczki
- ✅ System wtyczek (16.11): manifest `sophia-plugin.json`, ładowanie z `plugins/` (wolumen `/plugins`),
  zgodność wersji i zależności, migracje we własnym schemacie przy włączeniu, `startup()` wtyczki,
  `portal.plugins` / `plugin_migrations` / `plugin_access`, `require_plugin(id, uprawnienie)`, strażnik
  wyłączonej wtyczki (404), moduły web ładowane dynamicznie (React od Sophii), panel → **Wtyczki**
  (włącz/wyłącz, uprawnienia dla grup i użytkowników), strony wtyczek w panelu także dla
  nie-administratorów, `scripts/server/plugin.sh` (install / list / remove), `docs/WTYCZKI.md`.
- ✅ Repozytorium `sophia-plugins`: wtyczka wzorcowa `przyklad` i **`egib`** — import GML (profil EGiB 2021,
  wysyłka w częściach, klauzula z sumą kontrolną, podgląd zmian, zakres: pełne obręby / lista działek,
  scalanie w jednej transakcji), rejestr: stan bieżący + historia, `dzialka_uzytek`, `dzialka_punkt`,
  zmiany EGiB, raport zmian dla listy działek. Próba na kopii bazy (plik całego powiatu,
  136 tys. obiektów): wczytanie ~1,5 min, scalanie ~1,5 min, ponowny import bez zmian 4 s, wykrycie
  zmienionej i usuniętej działki, ~93 MB w bazie (z punktami granicznymi).
- ✅ Rozszerzenia API wtyczek (0.4–0.8.1, `docs/WTYCZKI.md`): zakres danych z wtyczki (`scope_codes`),
  akcje w formularzu obiektu (`featureActions`), okna nad mapą, `host.currentProject()` / `currentExtent()`,
  układ górnego paska (`menu`, `order` — menu rozwijane), element w pasku narzędzi (`toolbar`), wygląd
  (`theme(project)`: arkusz CSS, logo, nazwa, ikona karty, panel warstw), zapis plików przez pyogrio
  (XLSX, CSV, GPKG, SHP).
- ✅ Nagłówki `X-Portal-User` / `X-Portal-Groups` do QGIS Server kodowane procentowo (polskie nazwy grup
  dawały błąd 500 kafli).
- ✅ Ogólne wtyczki w `sophia-plugins`: **`wyszukiwarka`** 1.1.1 (pole „Szukaj” w pasku narzędzi, warstwy
  i pola wskazane dla projektu, wyniki w zakresie użytkownika), **`eksport`** 1.1.0 (XLSX, CSV, GeoPackage,
  paczka mLas; cały zakres albo bieżący widok; zestawienia innych wtyczek; dziennik pobrań), **`wyglad`**
  1.0.1 (motywy Sophia / Grafit / Lasy Państwowe, edytor motywów, logo PNG/WEBP, ikona karty, wyłączalna
  nazwa, motyw i panel warstw dla projektu).
- ✅ **`prg`** 1.0.0 (22.11): obręby ewidencyjne i nadleśnictwa z Państwowego Rejestru Granic w schemacie
  `prg` — usługa WFS GUGiK (obszar: TERYT / kod RDLP, w tle, stronami) albo paczka SHP/GML; podgląd zmian,
  zakres pełny / uzupełnienie, kontrola duplikatów (identyfikator IIP, unikalny kod), stan bieżący + historia;
  porównanie z tabelą z innego źródła (np. dane Lasów Państwowych; po kodzie albo po położeniu, tolerancja)
  z warstwą rozbieżności `prg.v_roznice_ostatnie`.

### ✅ Wydajność mapy z filtrem zakresu danych
Analiza i zmiany 22.11, wdrożone (wyłączenia, użytkownik z jednym nadleśnictwem): render z filtrem +0–0,15 s na obraz, autoryzacja `/ows` ~4 ms, naprzemienni użytkownicy bez kary.
- ✅ obraz wektorów w 1:1 (`ImageWMS` `hidpi: false`, `ratio` 1,1) — wcześniej np. 3780×1458 px na HiDPI,
  0,5–0,65 s przy każdym przesunięciu; teraz ok. 4× mniej pikseli,
- ✅ źródło narzutu filtra na warstwie użytków EGiB: QGIS sprawdza unikalność klucza widoku
  (`checkPrimaryKeyUnicity`) przy każdej zmianie filtra — z filtrem przestrzennym 105 ms (bez 8 ms). Fia →
  Diagnostyka: ostrzeżenie i przycisk „Wyłącz sprawdzanie unikalności klucza w widokach”,
- ✖ podzielone granice zakresu (`ST_Subdivide`) — sprawdzone i odrzucone: na danych produkcji filtr na całej
  granicy kosztuje 1–3 ms (PostGIS cache'uje przygotowaną geometrię), a pocięcie granic całego kraju 20 s,
- ✅ dziennik czasów `/ows` w Caddy + `scripts/server/ows-report.sh` (mediana, p95, rozmiar, błędy),
- ✅ strojenie QGIS Server przy starcie z CPU i pamięci kontenera (`config/qgis-start.sh`, nadpisanie
  `SOPHIA_QGIS_*` w `.env`) — działa tak samo na serwerze RDLP o innej liczbie rdzeni.

### ✅ Serwer i wdrożenie
- ✅ `config/pg_service.conf` poza gitem, w repo `pg_service.conf.example` (d5478d1). Plik musi być
  czytelny dla QGIS Server (`chmod 644`; od 12.11 do 15.11 prawa 600 psuły warstwy PostGIS, ffc1245).
