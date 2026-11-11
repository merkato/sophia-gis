# TO DO — WebUI i Fia

Lista z 10.11.2026 (aktualizacja 11.11.2026). Kolejność jest kolejnością realizacji.

## Główne zadania

### 1. ✅ Edytor atrybutów jako okno na środku ekranu (a048d5b)
- Formularz obiektu (atrybuty, powiązane, dokumenty) jako okno modalne / pływające na środku,
  zamiast panelu przy prawej krawędzi. Mapa pod spodem nadal widoczna (półprzezroczyste tło
  albo okno przesuwalne).
- Na telefonie: pełny ekran.
- Dotyczy: `web/src/components/FeaturePanel.tsx`, `App.tsx`, `styles.css`.

### 2. ✅ Po zapisie kliknięcie w inny obiekt wczytuje go do formularza (1a90dd1)
- Teraz po zapisie formularz zostaje otwarty na zapisanym obiekcie, a kolejne kliknięcie
  na mapie go nie podmienia.
- Oczekiwane: jeśli w formularzu nie ma niezapisanych zmian, kliknięcie (identyfikacja albo
  „Wybierz”) wczytuje nowy obiekt. Przy niezapisanych zmianach pytamy: zapisz / odrzuć / anuluj.

### 3. ✅ Fotografie, także z aparatu telefonu/tabletu (08a7116)
- Załącznik typu zdjęcie: `<input type="file" accept="image/*" capture="environment">`
  otwiera aparat w przeglądarce mobilnej.
- Po stronie serwera: JPEG/PNG/HEIC (konwersja HEIC → JPEG), zmniejszenie do rozsądnego
  rozmiaru, miniatury, EXIF (data, GPS, orientacja). Galeria w formularzu.
- Zrobione inaczej niż w planie: bez ustawienia w Fii — pole z widżetem QGIS „Załącznik” (wariant A)
  albo tabela zdjęć w relacji (wariant B), galeria z wizytacjami, pobieranie do QGIS przez Fię.
  Opis: `docs/user/zdjecia.md`.

### 4. ✅ Ikony zamiast napisów na przyciskach (razem z punktem 7)
- Uniwersalne, w stylu QGIS (zestaw ikon SVG w repo, np. na licencji zgodnej z QGIS):
  wybierz, rysuj punkt / linię / poligon, zmień geometrię, usuń, zapisz, identyfikacja,
  pomiar, wydruk, warstwy, podkłady.
- Podpowiedź (`title` / tooltip) z pełną nazwą przy każdej ikonie.
- Zrobione: własne SVG w stylu QGIS (`web/src/components/Icons.tsx`) — bez kopiowania grafik QGIS (GPL).
  Pomiar i wydruk dojdą do paska razem z tymi narzędziami.

### 5. ✅ Załączniki (PDF i inne) z WebUI — osobny katalog na projekt
- **Stan obecny:** WebUI już dodaje PDF (zakładka „Dokumenty” w formularzu), jeśli warstwa ma
  w Fii zaznaczone „Załączniki PDF”. Ograniczenia: tylko PDF (sprawdzanie `%PDF-`), pliki we
  wspólnym wolumenie `attachments` (`xx/yy/<uuid>.pdf`), nie w katalogu projektu.
- Zrobione jak zdjęcia (`docs/user/zalaczniki.md`): pole „Załącznik” bez podglądu obrazu albo tabela
  dokumentów w relacji; typy z filtra plików widżetu QGIS; pliki bez zmian w `data/uploads/<slug>/pliki`;
  stary mechanizm „Załączniki PDF” usunięty (na serwerze nie było plików). Limit per warstwa — z punktem 8.
- Pierwotny plan: dozwolone typy konfigurowane w Fii (PDF, obrazy, DOCX/ODT, ZIP…), limit
  rozmiaru per warstwa, katalog uploadów per projekt (np. `data/uploads/<slug>/…`),
  uwzględnienie w kopii zapasowej, podgląd/pobieranie z formularza.

### 6. ✅ Narzędzie ULDK: działka z kliknięcia do warstwy projektu
- Kliknięcie w mapę → zapytanie do ULDK (GUGiK, `uldk.gugik.gov.pl`, `GetParcelByXY`) →
  pokazanie działki (obrys na mapie, identyfikator TERYT, obręb, gmina) → pytanie „Dodać
  do warstwy …?” → zapis geometrii i atrybutów do warstwy wskazanej w Fii.
- Konfiguracja w Fii (nowa zakładka „Narzędzia pobierania”): warstwa docelowa, mapowanie
  pól (TERYT, numer, obręb, gmina, powiat, województwo…), czy otwierać formularz po dodaniu.
- **Architektura rozszerzalna:** wspólny mechanizm „pobierz obiekt z usługi zewnętrznej
  i dodaj do warstwy” z wtyczkami źródeł (ULDK działki, ULDK budynki, PRG adresy, BDOT…).
  Każde źródło: zapytanie po punkcie/identyfikatorze, normalizacja wyniku, mapowanie pól z Fii.
  Zapytania przez API Sophii (bez CORS, z logiem i limitem).
- Zrobione: `api/app/fetchers.py` (źródła ULDK działka i budynek), `routers/fetch.py`, zakładka Fii
  „Narzędzia pobierania” (`fia/tools.py`), przycisk na pasku i karta wyniku w WebUI; `docs/user/uldk.md`.
  Kolejne źródła (PRG adresy, BDOT10k) — nowy wpis w SOURCES i w `fia/tools.py`.

### 7. ✅ Górny pasek narzędzi edycji
- Wszystkie narzędzia edycyjne (wybierz, rysuj, zmień geometrię, usuń, ULDK…) w pasku
  u góry ekranu zamiast w panelu bocznym.
- Gdy żadna warstwa nie jest aktywna do edycji, narzędzia są **wyszarzone** (nie znikają).
- Wybór aktywnej warstwy edycyjnej: z drzewa (ołówek) i z listy w pasku.

### 8. ✅ Model uprawnień: serwer → projekt → zakres danych
Potrzebny do projektów z podziałem danych na jednostki terenowe (centrala widzi wszystko, oddziały — swoje).
- **Serwer:** administrator zawsze wszystko; flaga **Autor projektów** przy użytkowniku — publikacja
  przez Fię bez pełnych praw administratora.
- **Projekt (grupa w projekcie):** rola podgląd / edycja, prawo do zdjęć i PDF (domyślnie włączone),
  wyjątki per warstwa (już są: `layer_access`).
- **Zakres danych (grupa w projekcie):** „cały obszar” albo lista kodów (np. `od01`, `od02`).
  W Fii autor definiuje **wymiar zakresu** (warstwa granic + pole z kodem) i regułę dla każdej
  warstwy: *przestrzennie* (dokładna geometria, nie bbox), *atrybut* (pole = kod), *przez relację*
  (dziedziczy po obiekcie nadrzędnym — oględziny, zdjęcia, PDF), *bez filtra* (słowniki).
- Granica: widzi każda jednostka, której obszar obiekt przecina; edytuje ta, w której obszarze leży punkt
  wewnętrzny obiektu (jeden właściciel). Kilka grup = suma zakresów.
- **Jeden filtr wszędzie:** API (lista, odczyt, edycja, powiązane, zdjęcia, PDF), **QGIS Server**
  (mapa, identyfikacja, wydruk — wtyczka kontroli dostępu z filtrem SQL od API; dziś zasięgi
  działają tylko w API, obraz mapy pokazuje wszystkie obiekty!), pobieranie zdjęć przez Fię, raporty.
- Kolejność: silnik filtra w API → filtr w QGIS Server → model danych i migracja obecnych zasięgów
  (`extents`, `extent_assignments`) → Fia i panel administratora → dokumentacja na fikcyjnym przykładzie.
- Wchłania zaległe: zasięg obiektu nadrzędnego dla tabel bez geometrii.
- Zrobione: `api/app/scope.py` (jeden warunek SQL dla API i QGIS Server), wtyczka
  `qgis-server-plugins/sophia_filter`, migracja `permissions_v2`, panel (autor projektów, grupy i zakres),
  Fia (zakładka „Zakres danych”), `docs/user/uprawnienia.md`. Stare zasięgi (`extent_assignments`)
  wycofane. Limit wielkości plików per warstwa — nie zrobiony (globalne limity w konfiguracji API).

### 9. ✅ Tabela atrybutów zamiast listy rekordów w panelu bocznym
- Usunąć listę rekordów tabel bez geometrii z panelu bocznego (`RecordList`). Przy dużej tabeli
  z kilkunastoma atrybutami lista z jedną etykietą nie wystarcza.
- Kliknięcie warstwy w panelu bocznym (lub ikona „Otwórz tabelę atrybutów” na pasku, jak w QGIS)
  otwiera **tabelę atrybutów na środku ekranu**: okno przesuwane jak formularz obiektu, na telefonie
  pełny ekran.
- **Sortowanie** po kliknięciu nagłówka kolumny (rosnąco / malejąco).
- **Ukrywanie kolumn** przez użytkownika — tymczasowe (bez zapisu w projekcie; najwyżej zapamiętane
  w przeglądarce).
- Kliknięcie wiersza otwiera rekord w formularzu (z pytaniem o niezapisane zmiany), „Dodaj rekord”
  z paska działa jak dotąd. Także dla warstw z geometrią (wiersz → przybliżenie do obiektu).
- Wyszukiwanie / filtr, stronicowanie po stronie API dla dużych tabel.
- Zrobione: `AttributeTable.tsx`, wspólne okno `FloatingWindow.tsx`, API listy z `offset/sort/desc/q/
  geometry/total`; `RecordList` usunięty; opis w `docs/user/README.md`.

## Zaległe z wcześniejszych dni

- [ ] Edytor schematu bazy w WebUI (tabele, kolumny, relacje, słowniki) — patrz ARCHITECTURE.md.
- [ ] `sync-rasters.ps1`: wysyła nowe arkusze biblioteki, przebudowuje VRT i piramidy,
      restartuje QGIS Server i czyści cache kafli.
- [x] Podkład z katalogu w wydruku widoku mapy — wydruk w przeglądarce (`web/src/print.ts`): bieżący widok
      z podkładami i warstwami na A4/A3, tytuł, skala, podziałka, data, źródła. QGIS Server 4.2 nie tworzy
      warstw zewnętrznych (`EXTERNAL_WMS:`), a żaden projekt nie ma szablonu wydruku.
- [ ] Sprzątanie plików osieroconych w `data/uploads` (zdjęcie usunięte z pola/rekordu zostaje na dysku).
- [ ] `config/pg_service.conf` poza gitem (w repo tylko `pg_service.conf.example`), żeby
      hasło na serwerze nie blokowało `git pull`.
- [x] Mapa (z podkładami) także bez wybranego projektu / dla niezalogowanych (razem z wydrukiem).

## Na sam koniec

- [ ] **Raporty po stronie Sophii** (zamiast raportów z menedżera wydruków QGIS) — np. raporty
      z oględzin terenowych do PDF, z filtrem zakresu użytkownika (punkt 8). Najpierw analiza
      dotychczasowego rozwiązania raportów w projekcie, który będzie przenoszony.
