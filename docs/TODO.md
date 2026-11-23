# TO DO — Sophia (WebUI, API, Fia)

Aktualizacja 22.11.2026 (wdrożona Sophia 0.8.2). Na górze plan (kolejność = kolejność realizacji), niżej zrobione — tematycznie.
Tylko rdzeń Sophii i ogólne wtyczki z `sophia-plugins`; prace wtyczek branżowych (np. wyłączenia) — w ich repozytoriach.

Oznaczenia: ✅ zrobione · ✔️ zrobione częściowo (co zostało — w planie) · ⬜ do zrobienia

---

## Plan

### ⬜ 1. Do przetestowania (zrobione, nieprzetestowane w pełni)
- ⬜ Narzędzia edycji geometrii w przeglądarce na prawdziwych danych, cofanie (Ctrl+Z).

### ⬜ 2. Drobne zaległości
- ⬜ Kolejne źródła narzędzi pobierania: PRG adresy, BDOT10k (nowy wpis w `SOURCES` i w `fia/tools.py`).
- ⬜ Przyciąganie i kontrola topologii w edycji — **od początku, na każdej warstwie edycyjnej** (ustalenia 23.11):
  - przyciąganie do węzłów (i krawędzi) istniejących geometrii: warstwy edycyjnej i wskazanych warstw odniesienia
    (np. kontur → działki, użytki, inne kontury; użytek → działki, inne użytki; działka z dnia decyzji → działki);
    zestaw warstw i tolerancja z ustawień przyciągania projektu QGIS, przełącznik w aplikacji;
  - kontrola topologii przy zapisie (nakładanie z innymi obiektami warstwy, wyjście poza obiekt nadrzędny
    w tolerancji) — komunikat z miejscem błędu na mapie;
  - usuwanie wierzchołków wygodniej niż Alt+klik (np. zaznaczenie + Delete);
  - nakładka działek z powiatów (KIEG, WMS) jako warstwa odniesienia — podgląd; przyciąganie tylko do danych
    wektorowych (rejestr EGiB / ULDK w bazie).

### ⬜ 3. Graficzny edytor schematu bazy (WebUI) — plan z 15.11
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
