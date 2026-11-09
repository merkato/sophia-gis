# Architektura Sophii

## Założenia (czego nie powtarzamy po Lizmapie)

| Problem w Lizmap | Rozwiązanie tutaj |
|---|---|
| Każdą warstwę trzeba ręcznie skonfigurować we wtyczce, inaczej nie istnieje | **Projekt QGIS jest jedynym źródłem prawdy.** API samo czyta drzewo warstw, pola, aliasy, widżety formularzy, ograniczenia NOT NULL, relacje i wydruki z `.qgz`. Plik `.portal.json` zawiera wyłącznie *nadpisania* (co edytowalne, gdzie PDF, które grupy to mozaiki). Brak pliku = działające ustawienia domyślne. |
| Edycja przez WFS-T: kapryśna, zależna od ustawień QGIS Server, słaba kontrola uprawnień | **Edycja z pominięciem WFS-T.** API zapisuje bezpośrednio do PostGIS (psycopg, zapytania budowane przez `sql.Identifier`) — walidacja pól, zasięgi przestrzenne i relacje w jednej transakcji. QGIS Server tylko renderuje. |
| Relacje działają tylko przy określonej konfiguracji „attribute layers” | Relacje odczytywane z `<relations>` projektu; formularz ma zakładkę „Powiązane”; relacje typu *Composition* kasują dzieci razem z rodzicem. |
| Ciche błędy konfiguracji | **Diagnostyka** we wtyczce i w API (`/api/admin/projects/{id}/diagnostics`): brak `service=`, brak klucza głównego, nieznany SRID, relacje między bazami, ścieżki bezwzględne, rastry bez piramid. |
| Hasła do bazy w projektach | Wymuszone `service=sophia` z `pg_service.conf` — ten sam plik `.qgz` działa na desktopie i w kontenerze. |

## Wersje QGIS

* **Cel: QGIS 4.x (Qt6).** Serwer domyślnie `camptocamp/qgis-server:4.2`; LTR 3.44 możliwy przez `QGIS_SERVER_IMAGE`.
* Wersja QGIS Server musi być **≥** wersji Desktop, w której zapisano projekt.
* Wtyczka działa w QGIS 3.40–4.x: wyłącznie w pełni kwalifikowane enumy Qt (`Qt.CheckState.Checked`,
  `QHeaderView.ResizeMode.Stretch`…), `Qgis.WkbType`, `serverProperties()`; `supportsQt6=True` w `metadata.txt`.
* API nie używa PyQGIS — czyta XML projektu, więc nie zależy od wersji Qt. Testy parsera obejmują format 4.x.

## Komponenty

```
                 ┌──────────────────────────── Caddy (SSL, Let's Encrypt) ────────────────────────────┐
 przeglądarka ──►│  /            → web  (nginx, SPA React + OpenLayers)                               │
                 │  /api/*       → api  (FastAPI)                                                     │
                 │  /ows?PROJECT → forward_auth api:/api/ows/authorize → qgis (QGIS Server, MAP=…)    │
                 └────────────────────────────────────────────────────────────────────────────────────┘
                                         │                         │
                               ┌─────────▼──────────┐    ┌─────────▼─────────┐
                               │ PostgreSQL/PostGIS │◄───┤ QGIS Server       │  /projects (ro), /rasters (ro)
                               │  schemat portal    │    └───────────────────┘
                               │  + dane GIS        │
                               └────────────────────┘
 QGIS Desktop + wtyczka ──(HTTPS, Bearer)──► /api/admin/publish  → data/projects/<slug>/<slug>.qgz + .portal.json
```

* **QGIS Server** nie ma publicznego portu. Każde żądanie OWS przechodzi przez `forward_auth`: API sprawdza
  token (ciasteczko HttpOnly), dostęp do projektu i nazwy warstw (`LAYERS`, `QUERY_LAYERS`, `TYPENAME`),
  blokuje `Transaction` i `GetPrint`, a następnie podaje ścieżkę pliku projektu. Klient zna tylko `PROJECT=<slug>`,
  parametr `MAP` od klienta jest zawsze nadpisywany.
* **API** (`api/app`):
  * `qgsproject.py` — parser `.qgs/.qgz` (lxml, bez PyQGIS), cache unieważniany po zmianie pliku,
  * `permissions.py` — rola grupy w projekcie → nadpisania per warstwa → zasięgi,
  * `routers/features.py` — CRUD GeoJSON, `bbox`, transformacje układów, relacje,
  * `routers/attachments.py` — PDF na wolumenie `attachments`, metadane + SHA-256 w bazie,
  * `routers/reports.py` — layouty QGIS przez `GetPrint` (atlas ⇒ raport dla obiektu),
  * `routers/admin.py` — użytkownicy, grupy, zasięgi, projekty, uprawnienia, publikacja.
* **WebUI** (`web/src`): wybór projektu z menu, drzewo warstw zgodne z QGIS (grupy, wzajemne wykluczanie,
  mozaiki rastrowe jako jeden węzeł), identyfikacja (GetFeatureInfo JSON), edycja (rysowanie punkt/linia/poligon,
  zmiana geometrii, przyciąganie), formularz wg widżetów QGIS (ValueMap, CheckBox, DateTime, Range, TextEdit
  wielowierszowy), zakładki: Powiązane, Dokumenty (PDF), Raporty.
* **Wtyczka QGIS** **Fia** (`fia/`): konfiguracja warstw/rastrów/raportów zapisywana w projekcie,
  diagnostyka, budowa VRT + piramid z katalogu GeoTIFF, publikacja jednym kliknięciem.

## Model uprawnień

1. **Administrator** — wszystko.
2. **Rola grupy w projekcie** (`portal.project_access`): `viewer` (podgląd) / `editor` (edycja warstw oznaczonych
   jako edytowalne) / `manager` (jak editor; zarezerwowane na zarządzanie projektem). Użytkownik w wielu grupach
   dostaje rolę najwyższą.
3. **Nadpisania per warstwa** (`portal.layer_access`): view/insert/update/delete, suma (OR) po grupach. Nadpisanie
   nie włączy edycji warstwy, która nie jest edytowalna w projekcie.
4. **Zasięgi przestrzenne** (`portal.extents` + `extent_assignments`, dla grupy lub użytkownika):
   * `edit` — insert/update/delete tylko gdy geometria leży w sumie zasięgów (`ST_CoveredBy`); przy update/delete
     sprawdzany jest też stan sprzed zmiany,
   * `view` — dodatkowo filtruje odczyt obiektów przez API.
   * Brak przypisań = brak ograniczenia.

## Rastry z wielu GeoTIFF

* **Grupa jako mozaika** — grupa w drzewie oznaczona w `.portal.json` → w portalu jeden przełącznik, do WMS
  wysyłana nazwa grupy (QGIS Server renderuje całą grupę).
* **VRT + piramidy** (zalecane przy dziesiątkach/setkach arkuszy) — wtyczka buduje `gdal.BuildVRT` i overviews
  JPEG/YCbCr; jedna warstwa, szybkie renderowanie. Pliki trafiają do `data/rasters` (montowane do QGIS Server).

## Konfiguracja `.portal.json`

```json
{
  "version": 1,
  "layers": {
    "dzialki_7a1f…": { "editable": true, "attachments": true, "popup": true, "hidden": false }
  },
  "raster_groups": ["Ortofotomapa 2024"],
  "reports": [{ "layout": "Karta działki", "title": "Karta działki", "enabled": true }],
  "map": { "extent": [600000, 450000, 640000, 480000] }
}
```

## Ograniczenia v0.1 i roadmapa

**Etap 1 — uruchomienie (MVP, ten szkielet)**
- [ ] Pierwsze `docker compose up` i test na prawdziwym projekcie zapisanym w QGIS 4.2 (sprawdzić port 8080 obrazu)
- [ ] Panel administracyjny w WebUI (na razie tylko API + Swagger `/api/docs`)
- [ ] Testy integracyjne API na PostGIS w kontenerze (pytest + testcontainers)

**Etap 2 — edycja na poważnie**
- [ ] Zasięgi `view` także dla WMS/GetFeatureInfo: wtyczka serwerowa QGIS (`QgsAccessControlFilter`,
      `layerFilterSubsetString`) czytająca nagłówki `X-Portal-User/Groups` z proxy
- [ ] ValueRelation (słowniki z innych warstw), RelationReference, domyślne wartości (`default_expression`)
- [ ] Dodawanie obiektów potomnych z formularza rodzica, edycja tabel bez geometrii
- [ ] Narzędzia: dzielenie/łączenie poligonów, przyciąganie do innych warstw, wpisywanie współrzędnych, undo
- [ ] Blokada optymistyczna (wersja/`xmin`) przy równoczesnej edycji

**Etap 3 — eksploatacja**
- [ ] Cache kafli (WMTS z QGIS Server lub MapProxy) dla mozaik rastrowych
- [ ] Wyszukiwarka (pełnotekstowa po wskazanych polach), tabela atrybutów z filtrowaniem i eksportem
- [ ] Historia zmian obiektu z `audit_log`, przywracanie wersji
- [ ] Kopie zapasowe (pg_dump + wolumen załączników), monitoring
- [ ] Logowanie LDAP/OIDC (opcjonalnie)
