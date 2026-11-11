# Działki i budynki z ULDK

Narzędzie pobierania dodaje do warstwy projektu działkę ewidencyjną (albo budynek) wskazaną
kliknięciem na mapie. Dane pochodzą z usługi **ULDK** GUGiK (`uldk.gugik.gov.pl`): obrys, identyfikator
TERYT, numer działki, obręb, gmina, powiat, województwo. Nie trzeba ich przepisywać ani rysować.

Autor projektu ustawia w **Fii**, do której warstwy trafia geometria i do których pól trafiają
identyfikator TERYT i pozostałe dane. Użytkownik WebUI dostaje gotowy przycisk na pasku narzędzi.

## 1. Warstwa docelowa w bazie

Warstwa PostGIS z geometrią **poligonową** (obrys działki) albo **punktową** (punkt wewnątrz działki).
Przykład:

```sql
CREATE TABLE dane.dzialki (
    fid       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    teryt     text UNIQUE,          -- np. 999901_1.0001.123 (przykład)
    numer     text,                 -- 721
    obreb     text,                 -- Przykładowo
    obreb_nr  text,                 -- 0001
    gmina     text,                 -- Przykładowo
    powiat    text,
    uwagi     text,                 -- pozostałe pola uzupełniasz w formularzu
    geom      geometry(MultiPolygon, 2180) NOT NULL
);
```

- Kolumny na dane z ULDK mają być tekstowe (identyfikator TERYT zawiera kropki i podkreślenia).
- `UNIQUE` na kolumnie TERYT chroni przed dodaniem tej samej działki dwa razy. WebUI też to sprawdza,
  ale ograniczenie w bazie jest pewniejsze.
- Typ `MultiPolygon` albo `Polygon` — oba działają.

Dodaj warstwę do projektu i zaznacz ją w Fii jako **edytowalną** (zakładka *Warstwy*).

## 2. Narzędzie w Fii

*Web → Fia → zakładka **Narzędzia pobierania** → Dodaj narzędzie*:

| Ustawienie | Znaczenie |
|---|---|
| **Usługa** | *Działka ewidencyjna (ULDK)* albo *Budynek (ULDK)* |
| **Nazwa** | podpowiedź przycisku na pasku WebUI, np. „Działka z ULDK” |
| **Warstwa docelowa (geometria)** | warstwa, do której trafia obiekt (lista pokazuje warstwy PostGIS poligonowe i punktowe) |
| **Mapowanie pól** | dla każdej danej z usługi: pole warstwy albo „— nie zapisuj —” |
| **Po pobraniu otwórz formularz** | włączone: formularz nowego obiektu z wypełnionymi polami, użytkownik uzupełnia resztę i zapisuje; wyłączone: obiekt zapisuje się od razu |

Dane do zmapowania:

| Dana | Przykład (fikcyjny) | Działka | Budynek |
|---|---|---|---|
| Identyfikator (TERYT) | `999901_1.0001.123` / `999901_1.0001.45_BUD` | ✓ | ✓ |
| Numer działki | `721` | ✓ | |
| Obręb (nazwa) | `Przykładowo` | ✓ | ✓ |
| Obręb (numer) | `0001` | ✓ | ✓ |
| Gmina | `Przykładowo` | ✓ | ✓ |
| Gmina (TERYT) | `999901_1` | ✓ | ✓ |
| Powiat | `powiat przykładowy` | ✓ | ✓ |
| Województwo | `przykładowe` | ✓ | ✓ |

Fia sama podpowiada mapowanie, gdy pola warstwy mają typowe nazwy (`teryt`, `numer`/`nr_dzialki`,
`obreb`, `gmina`…). Pole, do którego trafia **identyfikator TERYT**, służy też do wykrywania
duplikatów, więc warto je zmapować zawsze.

Można dodać kilka narzędzi, np. „Działka z ULDK” do warstwy działek i „Budynek z ULDK” do warstwy
budynków. Każde dostaje własny przycisk.

Zapisz konfigurację i opublikuj projekt.

## 3. W WebUI

Na pasku narzędzi, za narzędziami edycji, pojawia się przycisk z obrysem działki i niebieską
strzałką (dla budynków — domek ze strzałką). Widzą go tylko użytkownicy, którzy mogą dodawać obiekty
do warstwy docelowej.

1. Włącz narzędzie i **kliknij na mapie** w miejscu działki.
2. Sophia pyta ULDK i pokazuje **niebieski przerywany obrys** oraz kartę z danymi: identyfikator,
   numer, obręb, gmina… i informację, do której warstwy i pól trafią.
3. **Dodaj do warstwy** — zależnie od ustawienia w Fii otwiera się formularz nowego obiektu
   z wypełnionymi polami (uzupełnij resztę i kliknij **Zapisz**) albo obiekt zapisuje się od razu.
4. Jeśli działka o tym identyfikatorze **już jest w warstwie**, karta to pokazuje: **Otwórz istniejący**
   albo **Dodaj mimo to**.
5. Kliknięcie w inne miejsce pobiera kolejną działkę. Ponowne kliknięcie przycisku albo **Anuluj**
   kończy pracę narzędzia.

Działka trafia do warstwy na tych samych zasadach co narysowana ręcznie: potrzebne jest prawo
dodawania obiektów, a obiekt musi leżeć w zasięgu przestrzennym użytkownika.

## Dobrze wiedzieć

- Zapytania do ULDK idą przez serwer Sophii (bez ograniczeń przeglądarki). Serwer zapisuje je w logu
  i ma limit **30 zapytań na minutę na użytkownika**, żeby nie przeciążać usługi GUGiK.
- ULDK czasem odpowiada wolno albo wcale. Wtedy karta pokazuje komunikat — spróbuj ponownie za chwilę.
- Geometria jest zapisywana w układzie warstwy (z ULDK przychodzi w EPSG:2180). Do warstwy punktowej
  trafia punkt leżący wewnątrz działki.
- Dane z ULDK to stan ewidencji z chwili pobrania. Sophia ich później sama nie aktualizuje.
- Kolejne źródła (np. adresy z PRG, obiekty BDOT10k) można dopisać w tym samym mechanizmie — każde
  dostanie własną listę danych do zmapowania w Fii.
