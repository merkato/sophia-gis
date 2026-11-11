# Dokumenty w obiektach (PDF, GML z podpisem, DOCX…)

Dokumenty działają tak samo jak [zdjęcia](zdjecia.md): te same dwa warianty konfiguracji w QGIS,
ten sam model uprawnień i to samo pobieranie do QGIS przez Fię. Różnice są dwie:

- serwer zapisuje plik **bajt w bajt**, bez żadnej konwersji. Podpis elektroniczny (np. XAdES w pliku
  GML) pozostaje ważny, a pobrany plik jest identyczny z wysłanym,
- dozwolone typy plików ustalasz **filtrem plików** w widżecie QGIS.

| | Wariant A: pole w tabeli obiektu | Wariant B: tabela dokumentów w relacji |
|---|---|---|
| Ile plików na obiekt | jeden (na każde pole) | dowolnie wiele |
| Gdzie w formularzu WebUI | zakładka **Atrybuty** | zakładka **Dokumenty (liczba)** |
| Opis, data, rodzaj dokumentu | nie | tak, jako zwykłe pola tabeli dokumentów |
| Kiedy wybrać | np. „skan decyzji” przy obiekcie | korespondencja, decyzje, operaty, kolejne wersje |

Sophia rozpoznaje pole na dokumenty po widżecie **Załącznik** **bez** podglądu „Obraz”. Pole
z podglądem „Obraz” to pole na zdjęcia — opis w [zdjecia.md](zdjecia.md).

---

## Wariant A — pole „Załącznik” w tabeli obiektu

```sql
ALTER TABLE dane.obiekty ADD COLUMN dokument text;
```

*Właściwości warstwy → Formularz atrybutów → pole `dokument`*:

1. **Typ widżetu:** **Załącznik** (Attachment).
2. **Zapisz ścieżkę jako:** **Ścieżka względna do projektu** (Relative to project path).
3. **Tryb zapisu:** **Ścieżki plików** (File paths).
4. **Zintegrowana przeglądarka dokumentów → Typ:** **Brak zawartości** (No content).
5. **Filtr plików** (File widget filter) — dozwolone typy, w formacie QGIS, np.:
   ```
   PDF (*.pdf);;GML z podpisem (*.gml *.xml);;Podpis XAdES (*.xades)
   ```
   - Bez filtra WebUI przyjmie każdy plik — poza zawsze blokowanymi wykonywalnymi i stronami WWW
     (`.exe`, `.bat`, `.js`, `.html`, `.svg`…).
   - Ten sam filtr ogranicza wybór plików w oknie przeglądarki i jest sprawdzany na serwerze.

W formularzu WebUI pole pokazuje nazwę pliku (kliknięcie otwiera PDF w przeglądarce, inne pliki są
pobierane) oraz przyciski **📎 Wybierz plik / Zmień plik** i **Usuń plik**. Plik jest przypisany do
obiektu po kliknięciu **Zapisz**.

## Wariant B — tabela dokumentów w relacji

```sql
CREATE TABLE dane.obiekty_dokumenty (
    fid          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    obiekt_fid   integer NOT NULL REFERENCES dane.obiekty (fid) ON DELETE CASCADE,
    plik         text NOT NULL,              -- ścieżka dokumentu (widżet Załącznik)
    rodzaj       text,                       -- np. decyzja, wniosek, operat (lista wartości)
    opis         text,
    dodano       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON dane.obiekty_dokumenty (obiekt_fid);
```

W QGIS:

1. Dodaj tabelę do projektu; pole `plik` ustaw jak w wariancie A.
2. `obiekt_fid` — widżet **Odwołanie do relacji**; `dodano` — **Data/czas**, nieedytowalne (lista
   dokumentów pokazuje datę i sortuje od najnowszych).
3. *Projekt → Właściwości → Relacje*: warstwa nadrzędna `obiekty` (`fid`), podrzędna
   `obiekty_dokumenty` (`obiekt_fid`). Nazwa relacji to nagłówek listy w WebUI.
4. Opublikuj projekt przez Fię; tabela dokumentów musi być edytowalna, żeby dodawać pliki.

W formularzu obiektu pojawia się zakładka **Dokumenty (liczba)**: lista plików z datą,
**📎 Dodaj pliki** (kilka naraz — każdy staje się osobnym rekordem), **✎** otwiera rekord dokumentu
(np. żeby uzupełnić rodzaj i opis), **✕** usuwa rekord.

Tabela może mieć jednocześnie pole na zdjęcia i na dokumenty, ale wtedy WebUI traktuje ją jako
tabelę zdjęć (galeria). Dla porządku: osobna tabela na zdjęcia, osobna na dokumenty.

---

## Uprawnienia, pliki na serwerze, QGIS

Wszystko jak przy zdjęciach ([zdjecia.md](zdjecia.md)):

- dokument widzi każdy, kto widzi **obiekt**, do którego jest dowiązany (projekt, warstwa, zasięg
  przestrzenny; w tabeli bez geometrii — zasięg obiektu nadrzędnego),
- dodawanie wymaga prawa edycji warstwy (wariant A) albo dodawania rekordów do tabeli dokumentów (B),
- pliki leżą w `data/uploads/<slug-projektu>/pliki/<tabela>/<rok-miesiąc>/<id>/<oryginalna nazwa>`
  i są w kopii zapasowej,
- **Fia → Pobierz zdjęcia z serwera** pobiera także dokumenty do folderu projektu — QGIS otwiera je
  z formularza (ścieżka względna),
- limit wielkości pliku: 50 MB,
- usunięcie dokumentu w WebUI nie kasuje pliku z dysku serwera.

## Zmiana względem wcześniejszej wersji

Dawne ustawienie Fii **„Załączniki PDF”** (zakładka „Dokumenty” bez konfiguracji w QGIS) zostało
usunięte — zastępuje je wariant A albo B. W kolumnie **Zdjęcia / pliki** w tabeli warstw Fia pokazuje
teraz, co wykryła w projekcie (pola „Załącznik” i tabele w relacji).
