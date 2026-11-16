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
          "pages": [{"id": "notatki", "title": "Notatki", "capability": "przyklad.podglad"}]}
}
```
- `id` = nazwa katalogu: małe litery, cyfry, `_`. Uprawnienia zaczynają się od `<id>.`.
- `sophia`, `requires` — warunki wersji (`>=1.0`, `<2`, `==1.2`, kilka po przecinku). Niespełnione →
  wtyczka nie ładuje się, panel pokazuje powód.

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
- Zależności Pythona: tylko biblioteki obecne w obrazie API Sophii (FastAPI, psycopg, lxml, pyproj…).

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
`api(ścieżka, init)` (względem `/api/plugins/<id>`), `request(pełna ścieżka, init)`, `notify(tekst)`.
Strony z `web.pages` pojawiają się jako zakładki panelu administracji u użytkowników z uprawnieniem
`capability`. Błąd w komponencie wtyczki nie wywraca panelu (izolacja błędów).

### Testy
W repozytorium wtyczek: `SOPHIA=../sophia scripts/test.sh` — pytest i ruff w obrazie API Sophii,
z kodem rdzenia z podanego katalogu.
