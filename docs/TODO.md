# TO DO — WebUI i Fia

Lista z 10.11.2026. Kolejność jest kolejnością realizacji (od 11.11.2026).

## Główne zadania

### 1. Edytor atrybutów jako okno na środku ekranu
- Formularz obiektu (atrybuty, powiązane, dokumenty) jako okno modalne / pływające na środku,
  zamiast panelu przy prawej krawędzi. Mapa pod spodem nadal widoczna (półprzezroczyste tło
  albo okno przesuwalne).
- Na telefonie: pełny ekran.
- Dotyczy: `web/src/components/FeaturePanel.tsx`, `App.tsx`, `styles.css`.

### 2. Po zapisie kliknięcie w inny obiekt wczytuje go do formularza
- Teraz po zapisie formularz zostaje otwarty na zapisanym obiekcie, a kolejne kliknięcie
  na mapie go nie podmienia.
- Oczekiwane: jeśli w formularzu nie ma niezapisanych zmian, kliknięcie (identyfikacja albo
  „Wybierz”) wczytuje nowy obiekt. Przy niezapisanych zmianach pytamy: zapisz / odrzuć / anuluj.

### 3. Fotografie, także z aparatu telefonu/tabletu
- Załącznik typu zdjęcie: `<input type="file" accept="image/*" capture="environment">`
  otwiera aparat w przeglądarce mobilnej.
- Po stronie serwera: JPEG/PNG/HEIC (konwersja HEIC → JPEG), zmniejszenie do rozsądnego
  rozmiaru, miniatury, EXIF (data, GPS, orientacja). Galeria w formularzu.
- Konfiguracja w Fii: warstwa „przyjmuje zdjęcia”.

### 4. Ikony zamiast napisów na przyciskach
- Uniwersalne, w stylu QGIS (zestaw ikon SVG w repo, np. na licencji zgodnej z QGIS):
  wybierz, rysuj punkt / linię / poligon, zmień geometrię, usuń, zapisz, identyfikacja,
  pomiar, wydruk, warstwy, podkłady.
- Podpowiedź (`title` / tooltip) z pełną nazwą przy każdej ikonie.

### 5. Załączniki (PDF i inne) z WebUI — osobny katalog na projekt
- **Stan obecny:** WebUI już dodaje PDF (zakładka „Dokumenty” w formularzu), jeśli warstwa ma
  w Fii zaznaczone „Załączniki PDF”. Ograniczenia: tylko PDF (sprawdzanie `%PDF-`), pliki we
  wspólnym wolumenie `attachments` (`xx/yy/<uuid>.pdf`), nie w katalogu projektu.
- Do zrobienia: dozwolone typy konfigurowane w Fii (PDF, obrazy, DOCX/ODT, ZIP…), limit
  rozmiaru per warstwa, katalog uploadów per projekt (np. `data/uploads/<slug>/…`),
  uwzględnienie w kopii zapasowej, podgląd/pobieranie z formularza.

### 6. Narzędzie ULDK: działka z kliknięcia do warstwy projektu
- Kliknięcie w mapę → zapytanie do ULDK (GUGiK, `uldk.gugik.gov.pl`, `GetParcelByXY`) →
  pokazanie działki (obrys na mapie, identyfikator TERYT, obręb, gmina) → pytanie „Dodać
  do warstwy …?” → zapis geometrii i atrybutów do warstwy wskazanej w Fii.
- Konfiguracja w Fii (nowa zakładka „Narzędzia pobierania”): warstwa docelowa, mapowanie
  pól (TERYT, numer, obręb, gmina, powiat, województwo…), czy otwierać formularz po dodaniu.
- **Architektura rozszerzalna:** wspólny mechanizm „pobierz obiekt z usługi zewnętrznej
  i dodaj do warstwy” z wtyczkami źródeł (ULDK działki, ULDK budynki, PRG adresy, BDOT…).
  Każde źródło: zapytanie po punkcie/identyfikatorze, normalizacja wyniku, mapowanie pól z Fii.
  Zapytania przez API Sophii (bez CORS, z logiem i limitem).

### 7. Górny pasek narzędzi edycji
- Wszystkie narzędzia edycyjne (wybierz, rysuj, zmień geometrię, usuń, ULDK…) w pasku
  u góry ekranu zamiast w panelu bocznym.
- Gdy żadna warstwa nie jest aktywna do edycji, narzędzia są **wyszarzone** (nie znikają).
- Wybór aktywnej warstwy edycyjnej: z drzewa (ołówek) i z listy w pasku.

## Zaległe z wcześniejszych dni

- [ ] Edytor schematu bazy w WebUI (tabele, kolumny, relacje, słowniki) — patrz ARCHITECTURE.md.
- [ ] `sync-rasters.ps1`: wysyła nowe arkusze biblioteki, przebudowuje VRT i piramidy,
      restartuje QGIS Server i czyści cache kafli.
- [ ] Podkład z katalogu w wydruku widoku mapy (GetPrint).
- [ ] `config/pg_service.conf` poza gitem (w repo tylko `pg_service.conf.example`), żeby
      hasło na serwerze nie blokowało `git pull`.
- [ ] Mapa (z podkładami) także bez wybranego projektu / dla niezalogowanych.
- [ ] Szew 5076 | 5077 (~30–50 m): dodatkowe punkty georeferencji po lewej stronie 5077.
