# Wtyczki Sophii

Funkcje potrzebne tylko części wdrożeń są **wtyczkami**: osobny kod, własny schemat w bazie, instalowane
przez administratora serwera i widoczne tylko dla wskazanych grup albo użytkowników. Ogólne wtyczki
żyją w publicznym repozytorium [`sophia-plugins`](https://github.com/merkato/sophia-plugins) (jedna
wtyczka = jeden katalog), wtyczki branżowe i klienckie — w osobnych repozytoriach o tym samym układzie.

## Dla administratora serwera

```bash
cd /opt/sophia
scripts/server/plugin.sh install https://github.com/merkato/sophia-plugins egib egib-v1.0.0
scripts/server/plugin.sh list
scripts/server/plugin.sh remove egib        # kod; dane w bazie zostają
```
`install` pobiera wskazany katalog z repozytorium (z tagu wersji), kopiuje go do `plugins/<id>`
(wolumen `/plugins` kontenera API) i restartuje API. Aktualizacja = ta sama komenda z nowym tagiem;
nowe migracje wykonają się przy starcie API, jeśli wtyczka jest włączona.

**Bezpieczeństwo:** kod wtyczki działa w procesie API z pełnym dostępem do bazy — instaluj tylko
z zaufanych repozytoriów i z konkretnego tagu. Dlatego instalacja jest krokiem na serwerze, a nie
przyciskiem w przeglądarce.

## W panelu administratora → Wtyczki

- lista zainstalowanych: wersja, wymagania (wersja Sophii, inne wtyczki), migracje do wykonania, błędy;
- **Włącz / Wyłącz** — włączenie wykonuje migracje (własny schemat wtyczki) i od razu udostępnia jej
  funkcje, bez restartu; wyłączenie ukrywa wtyczkę (API zwraca 404), dane zostają. Wtyczki zależne
  włącza się po wtyczce, od której zależą, a wyłącza — przed nią;
- **Ustawienia** — pola zadeklarowane przez wtyczkę w manifeście (np. projekt mapy), zapisywane w
  `portal.plugins.settings`;
- **Uprawnienia** — dla każdego uprawnienia wtyczki grupy i/lub pojedynczy użytkownicy. Administrator ma
  zawsze wszystkie. Użytkownik z uprawnieniem do strony wtyczki widzi przycisk „Administracja” i w nim
  tylko strony swoich wtyczek.

## Dla autora wtyczki

### Układ katalogu
```
<id>/
  sophia-plugin.json
  api/<pakiet>/__init__.py     # router FastAPI (zmienna `router`)
  migrations/001_*.sql         # SQL we własnym schemacie, wykonywany raz, w kolejności nazw
  web/index.js                 # moduł ES z `export function register(host)`
  tests/                       # testy (nie są kopiowane na serwer)
```

### Manifest `sophia-plugin.json`
```json
{
  "id": "przyklad",
  "name": "Przykład",
  "version": "1.0.0",
  "description": "…",
  "sophia": ">=0.1",
  "requires": {"egib": ">=1.0"},
  "capabilities": [{"id": "przyklad.podglad", "title": "Czytanie"}, {"id": "przyklad.zapis", "title": "Zapis"}],
  "api": {"package": "sophia_plugin_przyklad"},
  "web": {"entry": "web/index.js",
          "menu": "Przykład",
          "pages": [{"id": "notatki", "title": "Notatki", "capability": "przyklad.podglad"}]}
}
```
- `id` = nazwa katalogu: małe litery, cyfry, `_`. Uprawnienia zaczynają się od `<id>.`.
- `sophia`, `requires` — warunki wersji (`>=1.0`, `<2`, `==1.2`, kilka po przecinku). Niespełnione →
  wtyczka nie ładuje się, panel pokazuje powód.
- `settings` (opcjonalnie) — pola ustawień w panelu administratora:
  `[{"id": "projekt", "title": "Projekt mapy", "type": "project", "description": "…"}]`; typy `text`
  i `project` (lista projektów). Odczyt w API wtyczki: `await get_settings_for("<id>")` (`app.plugins`).

### API
Router montowany pod `/api/plugins/<id>`; wyłączona wtyczka zwraca 404 bez udziału jej kodu. Z rdzenia
korzysta przez pakiet `app`:
```python
from fastapi import APIRouter, Depends
from app.db import portal_conn                     # połączenie z bazą Sophii
from app.plugins import require_plugin, data_dir   # uprawnienie; katalog na pliki wtyczki
from app.security import CurrentUser

router = APIRouter()

@router.get("/notatki")
async def notatki(user: CurrentUser = Depends(require_plugin("przyklad", "przyklad.podglad"))):
    ...
```
- `require_plugin(id, uprawnienie)` — 403 bez uprawnienia; `require_plugin(id)` — dowolne uprawnienie wtyczki.
- `data_dir(id)` — `<uploads>/_plugins/<id>` na pliki wtyczki (poza katalogami projektów).
- Długie zadania (import plików) — w wątku na osobnym połączeniu, stan w tabeli wtyczki.
- Opcjonalnie `async def startup()` w pakiecie API — Sophia wywołuje ją przy starcie API (po migracjach,
  tylko dla włączonej wtyczki), np. żeby oznaczyć zadania przerwane restartem.
- Opcjonalnie `async def scope_codes(user, project_slug)` — **zakres danych użytkownika** w projekcie
  podany przez wtyczkę zamiast kodów z grup (Administracja → Projekty → Dostęp). Zwraca `None` (wtyczka nie
  dotyczy projektu), `"*"` (cały obszar) albo listę kodów wymiaru zakresu z Fii (pusta lista = nic).
  Grupy nadal decydują o roli (przeglądanie / edycja); administrator i właściciel projektu widzą wszystko.
  Filtr działa jak zakres z grup: lista obiektów, formularze, edycja, powiązane, zdjęcia i mapa (QGIS Server).
  Funkcja jest wołana przy każdym żądaniu do projektu — trzymaj wynik w krótkiej pamięci podręcznej.
- Opcjonalnie `async def upload_sets(project_slug)` (Sophia ≥ 0.8.2) — **zbiory plików** wtyczki w projekcie:
  `[{"id", "title", "kind": "photo" | "file"}]`. Pojawiają się w panelu → Projekty → Przechowywanie plików z limitem
  (domyślnie globalnym); wtyczka odczytuje go przez `await app.storage.limit_mb(slug, f"plugin:<id>:{id}", kind)`.
- Zależności Pythona: tylko biblioteki obecne w obrazie API Sophii (FastAPI, psycopg, lxml, pyproj, Pillow, WeasyPrint, pyogrio…).
- **PDF**: `app.pdf.html_to_pdf(html, title=…, author=…)` — dokument z HTML i CSS jako **PDF/A-2b** (czcionki
  osadzone, gotowy do podpisu elektronicznego). Strona, nagłówki, stopki i „Strona X z Y” w CSS (`@page`,
  `counter(page)` / `counter(pages)`), `<thead>` powtarza się na każdej stronie. Obrazy jako `data:` URI —
  zasoby z sieci i dysku są blokowane. Czcionki w obrazie: DejaVu Sans/Serif, Liberation Sans/Serif/Mono.
  Wołaj w wątku (`asyncio.to_thread`).

### WebUI
Moduł ES bez budowania (albo zbudowany do jednego pliku), ładowany dynamicznie. Sophia przekazuje
Reacta — paczka nie dołącza własnej kopii:
```js
export function register(host) {
  const h = host.React.createElement;
  function Notatki() { /* host.api("/notatki"), host.can("przyklad.zapis"), host.notify("…") */ }
  return { pages: { notatki: Notatki } };
}
```
`host`: `apiVersion` (1), `React`, `pluginId`, `user`, `capabilities`, `can(uprawnienie)`,
`api(ścieżka, init)` (względem `/api/plugins/<id>`), `request(pełna ścieżka, init)`, `notify(tekst)`,
`showOnMap(focus)` (Sophia ≥ 0.2) — zamyka panel administracji i pokazuje obiekt na mapie:
```js
host.showOnMap({
  project: "slug-projektu",                                  // brak = bieżący projekt
  targets: [{ table: "egib.v_dzialka", pk: "ULDK:…" }],      // warstwa projektu z tej tabeli → formularz obiektu
  geometry: { type: "MultiPolygon", coordinates: [...] },    // gdy warstwy nie ma: podświetlenie (EPSG:4326)
  label: "Działka …",
});
```
Ten sam obiekt można podać w adresie: `?p=<slug>&obiekt=<schemat.tabela>:<klucz>` (link do wysłania).
`host.startDraw({ project, table: "schemat.tabela", defaults: { pole: wartość }, geometry, label })` (Sophia ≥ 0.3) —
przybliża mapę i włącza rysowanie w warstwie z tej tabeli; po narysowaniu formularz ma wypełnione `defaults`
(warstwa bez geometrii: od razu formularz).
Sophia ≥ 0.8.5: `raster: { url, extent: [minx, miny, maxx, maxy], crs: "EPSG:2180", label }` — obraz (PNG/WEBP/JPEG,
np. GeoTIFF przetworzony przez wtyczkę) nad podkładami, pod warstwami projektu; mapa przybliża się do zasięgu,
w panelu warstw pojawia się „Obraz z pliku” (ukryj / usuń). `edit: { table, defaults }` — warstwa z tabeli staje się
widoczna i wybrana do edycji; nowe obiekty tej warstwy dostają pola `defaults`. Przykład (wtyczka wyłączeń):
`host.showOnMap({ raster: {…}, edit: { table: "wylaczenia.kontur", defaults: { znak_sprawy } } })`.
Sophia ≥ 0.8.6: `compare: [{ geometry, kind, label }]` — porównanie geometrii (EPSG:4326) na osobnej warstwie nad
projektem: `kind` „historyczna” (szara, przerywana), „aktualna” (pomarańczowa), „uwaga” (czerwona), `label` — podpis
na mapie. Mapa przybliża się do wszystkich; w panelu warstw „Porównanie geometrii” (ukryj / usuń). Łączy się
z `draw` i `edit` — np. rysowanie działki z dnia decyzji na tle działek aktualnych:
`host.showOnMap({ newTab: true, compare: [{ geometry, kind: "aktualna", label: "123/4" }], draw: { table, defaults } })`.

`newTab: true` otwiera mapę w nowej karcie (panel administracji zostaje na miejscu; obiekt przekazywany przez
pamięć przeglądarki, więc geometria może być duża).

**Akcje w formularzu obiektu** (Sophia ≥ 0.6): `register` może zwrócić
`featureActions: { "schemat.tabela": (obiekt) => [{ label, title?, run }] }` — przyciski nad atrybutami w formularzu
obiektów warstw z tej tabeli (np. „Decyzja (PDF)” przy konturze). `obiekt` = `{ table, pk, layerId, project,
properties }`. Moduły wtyczek z interfejsem ładują się w tle po zalogowaniu, więc akcje są od razu.
`host.currentProject()` (Sophia ≥ 0.6) — slug projektu otwartego w oknie mapy albo `null`.
`host.currentExtent()` (Sophia ≥ 0.7) — zasięg widoku mapy `{ bbox: [minX, minY, maxX, maxY], crs }` w układzie projektu.

**Okna nad mapą** (Sophia ≥ 0.3): `web.windows: [{"id": "decyzje", "title": "Decyzje", "capability": "…"}]` —
przycisk w górnym pasku otwiera okno (przeciągane, ze zmianą rozmiaru); `"toolbar": false` = okno bez przycisku,
otwierane z kodu: `host.openWindow("drzewo", { props: { id: 7 }, title: "Decyzja …" })`, `host.closeWindow(id)`.
`register` zwraca `{ pages, windows: { decyzje: Komponent } }`; komponent okna dostaje `{ host, props, close }`.
Układ górnego paska (Sophia ≥ 0.8): `"order": 100` — kolejność przycisków (rosnąco, brak = 500, także między
wtyczkami); `"menu": "Decyzje"` — okna o tej samej nazwie menu (także z różnych wtyczek) trafiają do jednego menu
rozwijanego na miejscu pierwszego z nich. Gdy użytkownik ma dostęp tylko do jednego okna z menu — zwykły przycisk.

**Element w pasku narzędzi** (Sophia ≥ 0.8): `register` może zwrócić `toolbar: Komponent` (props `{ host }`) — np. pole
wyszukiwania po prawej stronie paska narzędzi pod górnym paskiem. Klasa `toolbar-field` daje układ „etykieta, pole,
przycisk-ikona”. Komponent sam sprawdza uprawnienia (`host.can`) i zwraca `null`, gdy ich brak.

**Wygląd** (Sophia ≥ 0.8): pakiet API może mieć `async def theme()` — albo `async def theme(project)` (Sophia ≥ 0.8.1:
slug projektu otwartego w mapie albo `None`, np. osobny motyw dla projektu) — zwracającą `{"css", "logo", "title", "favicon"}`
(każde pole opcjonalne): adres arkusza stylów, logo w górnym pasku, nazwę aplikacji (pasek i tytuł karty) i ikonę
karty; od 0.8.1 także `"layers_panel": "open" | "closed"` — panel warstw po wczytaniu i po zmianie projektu
(użytkownik nadal może go przełączyć; na wąskim ekranie zawsze zamknięty). Sophia pyta o to bez logowania (`GET /api/theme`, także ekran logowania), więc te adresy muszą być publiczne
(endpointy wtyczki bez `require_plugin`). Arkusz nadpisuje zmienne CSS rdzenia: `--bg`, `--surface`, `--ink`, `--muted`,
`--line`, `--accent`, `--accent-ink`, `--danger`, `--edit` oraz paska: `--topbar-bg`, `--topbar-ink`, `--topbar-muted`,
`--topbar-btn`, `--topbar-btn-ink`, `--topbar-btn-line`, `--topbar-line`, `--brand-logo-height`; nazwę obok logo ukrywa
`.brand-name { display: none }`. Po zmianie wyglądu strona wtyczki wysyła `window.dispatchEvent(new Event("sophia-theme"))` —
Sophia wczytuje go ponownie bez przeładowania. Wygrywa pierwsza włączona wtyczka z niepustą odpowiedzią.

Menu panelu: wtyczka z kilkoma stronami ma jedną pozycję rozwijaną (`web.menu`, domyślnie nazwa wtyczki do „ — ”),
a strony — krótkie tytuły (np. „Rejestr”, „Import”).
Strony z `web.pages` pojawiają się jako zakładki panelu administracji u użytkowników z uprawnieniem
`capability`. Błąd w komponencie wtyczki nie wywraca panelu (izolacja błędów).

### Testy
W repozytorium wtyczek: `SOPHIA=../sophia scripts/test.sh` — pytest i ruff w obrazie API Sophii,
z kodem rdzenia z podanego katalogu.
