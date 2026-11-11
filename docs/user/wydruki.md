# Wydruki

Ikona drukarki na pasku narzędzi otwiera panel **Wydruk** obok mapy. Mapa zostaje aktywna: przy
stałej skali niebieska ramka pokazuje obszar wydruku, a przesuwając mapę ustawiasz, co znajdzie się
na kartce. Do wyboru są dwa rodzaje wydruku:

| | Szablon QGIS | Układ Sophii |
|---|---|---|
| Skąd | układ wydruku zapisany w projekcie QGIS | wbudowany w Sophię, nie wymaga konfiguracji |
| Wygląd | dowolny: logo, legenda, siatka, kilka map, tabele… | tytuł, mapa, północ, skala z podziałką, data, źródła |
| Papier | ten z szablonu | A4 / A3, pionowo lub poziomo |
| Podkład z katalogu | gdy projekt ma warstwę z tej samej usługi (niżej) | zawsze |
| Wynik | PDF z QGIS Server | strona do druku / zapisu jako PDF |

Wspólne ustawienia w panelu:

- **Skala** — *cały widok mapy* albo stała skala z listy: 1:500, 1:1 000, 1:2 000, 1:2 500, 1:5 000,
  1:10 000, 1:25 000, 1:50 000, 1:100 000, 1:250 000, 1:500 000. Środek wydruku = środek mapy.
- **Tytuł** i **opis** — trafiają do etykiet szablonu (niżej) albo do nagłówka układu Sophii.
- **Jakość** — 96 / 150 / 200 dpi (szablon QGIS także 300 dpi).
- Na wydruku są warstwy włączone w panelu warstw i wybrany podkład, w kolejności jak na ekranie.
  Każdy widzi tylko dane ze swojego zakresu ([uprawnienia](uprawnienia.md)).

Raporty **dla obiektu** (szablony z atlasem) są w formularzu obiektu, zakładka **Raporty**.

---

## Szablon wydruku w QGIS — krok po kroku

*Projekt → Menedżer układów wydruku → Utwórz* (albo *Nowy układ wydruku*). Nazwa układu to nazwa
szablonu na liście w Sophii (w Fii, zakładka **Raporty**, można ją zmienić i wyłączyć szablon).

### 1. Mapa główna

1. Dodaj mapę (*Dodaj element → Mapa*) i narysuj ją na stronie. **Rozmiar elementu mapy = obszar
   wydruku**: Sophia rysuje ramkę o tym rozmiarze przeliczonym na wybraną skalę.
2. **Mapa główna musi być pierwszą mapą dodaną do układu.** QGIS Server rozpoznaje mapy po kolejności
   (pierwsza = `map0`), nie po nazwie. Mapy przeglądowe, wycinki itp. dodawaj później.
3. *Właściwości elementu*:
   - **Identyfikator elementu**: `map0` — nie jest wymagany, ale wtedy wyrażenia w etykietach
     (`item_variables('map0')`) odnoszą się do tej samej mapy, którą ustawia Sophia,
   - **Zablokuj warstwy** i **Podążaj za motywem mapy** — **wyłączone**. Sophia podaje warstwy
     widoczne w przeglądarce; zablokowane warstwy albo motyw zastąpiłyby wybór użytkownika,
   - skala i zasięg zapisane w szablonie nie mają znaczenia — Sophia ustawia środek i skalę przy
     każdym wydruku. Zostaw np. widok całego projektu.

### 2. Tytuł i opis z Sophii

Dodaj etykiety (*Dodaj element → Etykieta*) i nadaj im **identyfikatory elementu**:

| Identyfikator | Treść z panelu Sophii |
|---|---|
| `tytul` | pole **Tytuł** |
| `opis` | pole **Opis** (np. stan na dzień, sygnatura sprawy) |

Tekst wpisany w QGIS jest wartością domyślną — Sophia go zastępuje. Gdy szablon nie ma takiej
etykiety, pole w panelu jest wyłączone. Wyrażenia `[% … %]` wpisane przez użytkownika w Sophii są
usuwane (nie wykonują się na serwerze); wyrażenia w etykietach szablonu działają normalnie.

### 3. Skala, podziałka, północ, data

- **Podziałka**: *Dodaj element → Podziałka*, *Mapa* = mapa główna, jednostki: metry,
  *Segmenty → Dopasuj szerokość segmentu* — podziałka dobierze się do każdej skali z listy.
- **Skala liczbowa**: etykieta z wyrażeniem
  `1:[% format_number(item_variables('map0')['map_scale'], 0) %]`
  (`map0` = identyfikator elementu mapy głównej).
- **Strzałka północy**: *Dodaj element → Strzałka północy*, powiązana z mapą główną.
- **Data wydruku**: etykieta `[% format_date(now(), 'dd.MM.yyyy') %]`.
- **Legenda**: *Dodaj element → Legenda*, *Mapa* = mapa główna; włącz *Automatyczna aktualizacja*,
  wtedy legenda pokazuje warstwy z wydruku (opcjonalnie *Filtruj legendę według zawartości mapy*).
- **Siatka współrzędnych**: we właściwościach mapy głównej, *Siatki* — działa w każdej skali.

### 4. Podkład z katalogu na wydruku z szablonu

QGIS Server drukuje tylko warstwy zapisane w projekcie. Żeby wybrany w Sophii podkład (np.
ortofotomapa z Geoportalu) był na wydruku z szablonu, **dodaj do projektu warstwę z tej samej
usługi** — tak samo, jak dodajesz ją do pracy w QGIS:

1. *Warstwa → Dodaj warstwę → WMS/WMTS*, ta sama usługa i warstwa co w katalogu podkładów Sophii
   (np. `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMTS/StandardResolution`, warstwa
   `ORTOFOTOMAPA`, zestaw macierzy `EPSG:2180`),
2. w Fii zaznacz ją jako **Tylko w QGIS** — w przeglądarce jest już w katalogu podkładów, nie
   zdubluje się na liście warstw,
3. opublikuj projekt.

Sophia dopasowuje warstwę po adresie usługi i nazwie warstwy i kładzie ją pod warstwami projektu.
Gdy projekt nie ma takiej warstwy, panel uprzedza, że podkład się nie wydrukuje — wtedy wydrukuj
w **Układzie Sophii**, który podkład z katalogu ma zawsze.

### 5. Sprawdzenie

W QGIS: *Eksport do PDF* z układu (atlas wyłączony). W Sophii: panel **Wydruk** → szablon →
skala → **Utwórz PDF**. Zmiany w szablonie są widoczne po ponownej publikacji projektu przez Fię.

## Dobrze wiedzieć

- Szablon może mieć dowolny format strony (A4, A3, A0, niestandardowy) — Sophia go nie zmienia.
- Pozostałe mapy szablonu (przeglądowe) pokazują to, co zapisano w QGIS (mogą mieć *Podgląd*
  zasięgu mapy głównej).
- Duże formaty w 300 dpi generują się kilkanaście–kilkadziesiąt sekund.
- Układ Sophii otwiera stronę w nowej karcie — jeśli nic się nie dzieje, zezwól przeglądarce na
  wyskakujące okna dla Sophii.
