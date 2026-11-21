# Sophia — dokumentacja użytkownika

Dla osób, które **przygotowują projekty w QGIS** (autor projektu) i **pracują w przeglądarce**
(WebUI). Instalacja i utrzymanie serwera są opisane osobno, dla administratora: [SERVER.md](../SERVER.md).

## Konfiguracja projektu w QGIS

| Temat | Co opisuje |
|---|---|
| [Uprawnienia i zakres danych](uprawnienia.md) | autor projektów, grupy w projekcie, zdjęcia/dokumenty, zakres (np. oddziały terenowe) |
| [Zdjęcia w obiektach](zdjecia.md) | pole „Załącznik” w tabeli albo tabela zdjęć w relacji, aparat w telefonie |
| [Wydruki](wydruki.md) | szablony wydruku QGIS (mapa główna, tytuł/opis, podkład) i układ Sophii |
| [Działki i budynki z ULDK](uldk.md) | kliknięcie na mapie → działka z TERYT do wskazanej w Fii warstwy |
| [Dokumenty w obiektach](zalaczniki.md) | PDF, GML z podpisem, DOCX… — te same dwa warianty, pliki bez zmian |

Zasady ogólne, wspólne dla wszystkich tematów:
- warstwy edytowalne w WebUI muszą pochodzić z **PostGIS**, z połączenia przez usługę `sophia`
  (`pg_service.conf`), i mieć klucz główny,
- formularz w WebUI powstaje z ustawień *Właściwości warstwy → Formularz atrybutów*: aliasy,
  widżety (lista wartości, odwołanie do relacji, data, pole wyboru, załącznik…), pola ukryte
  i tylko do odczytu, pola wymagane,
- relacje (*Projekt → Właściwości → Relacje*) dają w formularzu zakładki **Powiązane**, **Zdjęcia** i **Dokumenty**,
- **atrybucja** (źródło danych, np. „Biblioteka Przykładowa, domena publiczna”): *Właściwości warstwy
  → QGIS Server → Atrybucja* (tytuł i opcjonalny URL), a bez niej — *Metadane → Prawa*. Pokazuje się
  w prawym dolnym rogu mapy (ⓘ), gdy warstwa jest włączona, i w „Źródła” na wydruku w układzie Sophii.
  W szablonie QGIS dodaj ją sam jako etykietę. Po zmianie zapisz projekt i opublikuj go ponownie w Fii,
- przed publikacją sprawdź zakładkę **Diagnostyka** w Fii,
- hasło do Sophii Fia trzyma w **menedżerze uwierzytelniania QGIS** (zakładka **Serwer**,
  „Zapamiętaj…”). Służy do publikacji i do pobierania zdjęć.

## Praca w przeglądarce

### Panel warstw
- Na górze **warstwy projektu** (drzewo jak w QGIS), na dole **podkład** (jeden) i **nakładki**
  (np. cieniowanie terenu) z katalogu Sophii.
- **◐ Przezroczystość** — przy włączonych warstwach rastrowych (skany, mozaiki VRT), przy wybranym
  podkładzie i włączonych nakładkach. Kliknięcie rozwija suwak (0–100%), ↺ wraca do pełnego krycia.
  Ustawienie pamięta ta przeglądarka; uwzględnia je też wydruk w układzie Sophii.
- Warstwy wektorowe (punkty, linie, poligony) rysuje QGIS Server jednym obrazem — ich wygląd,
  także przezroczystość, ustawiasz w stylu warstwy w QGIS.

### Formularz obiektu
- Formularz otwiera się jako **okno nad mapą**. Przesuwasz je, ciągnąc za nagłówek, a dwuklik
  w nagłówek wraca na środek. Rozmiar zmieniasz w prawym dolnym rogu, przycisk **▁** zwija okno do
  paska. Na telefonie formularz zajmuje cały ekran.
- Mapa pod oknem działa dalej: kliknięcie innego obiektu (identyfikacja albo **Wybierz**) wczytuje
  go do formularza.
- Jeśli w formularzu są **niezapisane zmiany**, Sophia pyta: **Zapisz** / **Odrzuć** / **Anuluj**.
  To samo pytanie pojawia się przy zamykaniu formularza.

### Pasek narzędzi
Pod paskiem tytułu jest pasek narzędzi z ikonami w stylu QGIS. Nazwa każdego narzędzia pokazuje się
po najechaniu kursorem. Narzędzia edycji są zawsze na miejscu. Bez aktywnej warstwy edycyjnej są
wyszarzone.

| Ikona | Narzędzie | Odpowiednik w QGIS |
|---|---|---|
| warstwy (trzy arkusze) | pokaż / ukryj panel warstw i podkładów | panel Warstwy |
| niebieskie „i” | **Identyfikuj obiekty** — kliknięcie otwiera obiekt w formularzu | Identyfikuj obiekty |
| drukarka | **Wydruk** — szablon QGIS z projektu albo układ Sophii, stałe skale, ramka na mapie ([wydruki.md](wydruki.md)) | Układ wydruku |
| żółty ołówek + lista | **Włącz / zakończ edycję** i wybór warstwy edycyjnej | Przełącz edycję |
| przerywany prostokąt ze strzałką | **Zaznacz obiekt** warstwy edycyjnej | Zaznacz obiekty |
| zielony punkt / linia / poligon z gwiazdką | **Dodaj obiekt** — ikona zależy od typu geometrii warstwy | Dodaj obiekt punktowy / liniowy / poligonowy |
| tabela z zielonym plusem | **Dodaj rekord** — dla tabel bez geometrii | Dodaj rekord |
| poligon z czerwonym węzłem | **Narzędzie wierzchołków** — przeciąganie wierzchołków, klik na krawędzi dodaje wierzchołek, **Alt+klik** usuwa; zwykłe kliknięcie otwiera obiekt | Narzędzie wierzchołków |
| poligon ze strzałkami | **Przesuń obiekt** — przeciągnij cały obiekt | Przesuń obiekt |
| poligon i łuk ze strzałką | **Obróć obiekt** — przeciągnij wokół środka, **Shift** = co 15° | Obróć obiekt |
| dwa poligony, kopia na zielono | **Kopiuj obiekt** — przeciągnij kopię w nowe miejsce | Kopiuj i wklej / Duplikuj obiekt |
| poligon z czerwoną linią na granicy | **Przekształć obiekt** — linia, która dwa razy przecina granicę | Przekształć obiekty |
| poligon rozcięty czerwoną linią | **Podziel obiekty** — linia przez obiekt (poligon albo linię); szczegóły niżej | Podziel obiekty |
| dwa poligony w jednym obrysie | **Połącz obiekty** — kliknij kolejne obiekty, potem „Połącz” | Połącz zaznaczone obiekty |
| poligon z dziurą i gwiazdką | **Dodaj pierścień** — narysuj dziurę wewnątrz poligonu | Dodaj pierścień |
| dziura wypełniona na żółto | **Wypełnij pierścień** — dziura i nowy obiekt w niej (formularz) | Wypełnij pierścień |
| dziura z czerwonym krzyżykiem | **Usuń pierścień** — kliknij w dziurę | Usuń pierścień |
| dwie części z gwiazdką | **Dodaj część** — narysuj nową część obiektu otwartego w formularzu | Dodaj część |
| przekreślona część | **Usuń część** — kliknij część obiektu wieloczęściowego | Usuń część |
| czerwony kosz | **Usuń zaznaczony obiekt** (z potwierdzeniem) | Usuń zaznaczone |
| tabela z niebieskim nagłówkiem | **Otwórz tabelę atrybutów** warstwy edycyjnej | Otwórz tabelę atrybutów |
| niebieska strzałka w lewo | **Cofnij ostatnią operację** (też **Ctrl+Z**) — szczegóły niżej | Cofnij |
| obrys działki / domek z niebieską strzałką | **Pobierz z ULDK** — działka lub budynek z kliknięcia do warstwy ([uldk.md](uldk.md)) | — (wtyczki ULDK) |

### Wydruk
Ikona drukarki otwiera panel **Wydruk** obok mapy: szablon wydruku z projektu QGIS albo **Układ
Sophii** (A4/A3), skala z listy (1:500 … 1:500 000) albo cały widok, tytuł, opis, jakość. Przy stałej
skali niebieska ramka na mapie pokazuje obszar wydruku — przesuń mapę, żeby go ustawić. Opis
i przygotowanie szablonu w QGIS: [wydruki.md](wydruki.md).

### Mapa bez projektu
Na liście projektów jest pozycja **— bez projektu (same podkłady) —**: mapa z podkładami z katalogu
na całą Polskę, z przełączaniem podkładów i wydrukiem w układzie Sophii. Tak wygląda też Sophia dla
gościa, gdy nie ma żadnego publicznego projektu.

### Tabela atrybutów
- Otwierasz ją ikoną tabeli przy warstwie w panelu warstw (każda warstwa z bazy) albo ikoną
  **Otwórz tabelę atrybutów** na pasku (warstwa edycyjna).
- Okno leży nad mapą przy dolnej krawędzi; przesuwasz je za nagłówek jak formularz, dwuklik
  wraca na środek, **▁** zwija. Na telefonie zajmuje cały ekran.
- **Sortowanie**: kliknięcie nagłówka kolumny — rosnąco, drugie kliknięcie — malejąco, trzecie — bez
  sortowania. Sortuje serwer, więc dotyczy całej tabeli, nie tylko widocznej strony.
- **Szukaj** przeszukuje wszystkie kolumny (fragment tekstu); wynik też liczy serwer.
- **Kolumny ▾** — ukrywanie kolumn na czas pracy. Wybór zapamiętuje ta przeglądarka, projekt QGIS
  się nie zmienia.
- Wartości wyglądają jak w formularzu: etykiety list wartości i słowników, nazwy plików, ✓.
- Kliknięcie wiersza otwiera rekord w formularzu (z pytaniem o niezapisane zmiany), a dla warstwy
  z geometrią także przybliża mapę do obiektu.
- Strony po 100 wierszy (‹ ›); tabela pokazuje tylko rekordy z Twojego zakresu danych.

### Edycja
- Warstwę do edycji wybierasz na pasku narzędzi (lista obok ołówka) albo ołówkiem w drzewie warstw.
- Po zapisie nowego obiektu narzędzie wraca do **Zaznacz obiekt**.
- Tabela bez geometrii (słownik, tabela nadrzędna) po wybraniu do edycji otwiera się od razu jako
  tabela atrybutów; nowy rekord dodajesz przyciskiem **+ Dodaj rekord** w tabeli albo na pasku.
- Na telefonie panel warstw jest domyślnie schowany i otwiera się ikoną warstw.
- Podczas rysowania (dodawanie obiektu, linia podziału) **Esc** przerywa szkic, a **Backspace**
  cofa ostatni wierzchołek. Dwuklik kończy linię.

### Podział obiektów
- Narysuj linię przecinającą obiekt **na wylot**. Wierzchołki przyciągają się do obiektów warstwy.
- Gdy obiekt jest otwarty w formularzu, dzielony jest tylko on. Bez tego Sophia dzieli wszystkie
  obiekty, które linia przecina (przy więcej niż jednym pyta o potwierdzenie, najwyżej 50 naraz).
- **Największa część zostaje dotychczasowym obiektem**: ten sam identyfikator, zdjęcia, dokumenty
  i rekordy powiązane. Pozostałe części to nowe obiekty.
- Atrybuty nowych części wynikają z **polityki podziału** pól w QGIS (*Właściwości warstwy →
  Atrybuty*, kolumna polityki podziału; nazwy jak w angielskim QGIS):
  - *Duplicate* (domyślnie) — kopia z obiektu dzielonego, także pól spoza formularza,
  - *Default value* — wartość domyślna **z bazy** (wyrażenia domyślne QGIS nie są
    liczone),
  - *Unset field* — puste pole,
  - *Geometry ratio* — pola liczbowe (np. powierzchnia, liczba) dzielone proporcjonalnie
    do powierzchni części (dla linii — do długości), także w obiekcie dotychczasowym.
- Wszystko w jednej operacji: jeśli któraś część wypadłaby poza Twój zakres danych albo linia
  nie dzieli obiektu, nic się nie zmienia.

### Pierścienie, części, łączenie, przesuwanie
Narzędzia poniżej działają na obiekcie otwartym w formularzu, a bez niego — na obiekcie, który
wskazuje szkic albo kliknięcie. Każda operacja jest pojedyncza: przy błędzie (szkic poza obiektem,
wynik poza Twoim zakresem danych) nic się nie zmienia i pojawia się komunikat.
- **Dodaj pierścień** — narysuj poligon w całości **wewnątrz** obiektu. Nie może przecinać granicy
  ani istniejącej dziury.
- **Wypełnij pierścień** — jak wyżej, a potem otwiera się formularz **nowego** obiektu w tej dziurze
  (obrys widać na niebiesko). Dziura wycina się dopiero przy zapisie formularza; zamknięcie
  formularza bez zapisu niczego nie zmienia.
- **Usuń pierścień** — kliknij wewnątrz dziury: obiekt odzyskuje tę powierzchnię. Jeśli dziurę
  wypełniał inny obiekt, zostaje on bez zmian (obiekty będą na siebie zachodzić).
- **Usuń część** — dla warstw z obiektami wieloczęściowymi (Multi…): kliknij część, Sophia pyta
  o potwierdzenie. Ostatniej części nie da się usunąć — wtedy usuń cały obiekt.
- **Połącz obiekty** — klikaj kolejne obiekty (fioletowe wyróżnienie, ponowne kliknięcie zdejmuje),
  na górze mapy pasek z listą i przyciskiem **Połącz**. **Pierwszy kliknięty zostaje**: jego klucz
  i atrybuty, a zdjęcia, dokumenty i rekordy powiązane pozostałych przechodzą do niego; pozostałe
  obiekty są usuwane. Warstwa z obiektami jednoczęściowymi przyjmie tylko obiekty, które się stykają.
  Wymaga prawa zmiany i usuwania.
- **Przesuń obiekt** — przeciągnij obiekt; zapis od razu po puszczeniu, jak przy wierzchołkach.
- **Obróć obiekt** (linie i poligony) — chwyć obiekt i przeciągnij wokół jego środka; z **Shift**
  kąt skacze co 15°. Zapis po puszczeniu.
- **Kopiuj obiekt** — przeciągnij obiekt: oryginał zostaje na miejscu, w nowym miejscu powstaje
  kopia i otwiera się w formularzu. Atrybuty kopii wynikają z **polityki duplikowania** pól w QGIS
  (*Duplicate* / *Default value* — wartość domyślna z bazy / *Unset field* — puste). Zdjęcia,
  dokumenty i rekordy powiązane zostają przy oryginale.
- **Przekształć obiekt** (linie i poligony) — narysuj linię, która **dwa razy przecina** granicę
  obiektu. Poligon: linia na zewnątrz dokłada obszar między linią a granicą, linia wewnątrz
  odcina mniejszą część. Linia: odcinek między przecięciami zastępuje narysowany fragment.
  Linia, która raz wychodzi, a raz wchodzi, jest odrzucana.
- **Dodaj część** — warstwy z obiektami wieloczęściowymi. Otwórz obiekt w formularzu (Zaznacz
  obiekt), potem narysuj część. Nowa część poligonu nie może nachodzić na obiekt ani stykać się
  z nim krawędzią.

### Cofanie
- **Cofnij** (strzałka na pasku albo **Ctrl+Z** poza polami formularza) odwraca Twoją **ostatnią
  operację** w projekcie: zapis formularza, dodanie, usunięcie, zmianę geometrii, podział,
  połączenie (razem z przeniesionymi zdjęciami), pierścień… Przed cofnięciem Sophia pokazuje, czego
  dotyczy, i pyta o potwierdzenie. Kolejne cofnięcia sięgają dalej wstecz (do 7 dni).
- Cofasz tylko własne zmiany. Jeśli ktoś (albo Ty) zmienił obiekt po tej operacji, cofnięcie się nie
  wykona — nie nadpisze późniejszej pracy.
- Usunięty obiekt wraca pod tym samym identyfikatorem, z polami widocznymi w formularzu; pola
  ukryte dostają wartość domyślną z bazy. Pliki zdjęć zostają na serwerze przez 7 dni, więc wraca też
  zdjęcie z pola „Załącznik”.

### Wtyczki
Część funkcji to wtyczki instalowane na serwerze (np. **EGiB** — import plików GML od starostw i rejestr
działek z historią). Administrator włącza je w panelu **Administracja → Wtyczki** i wskazuje, które grupy
albo osoby mogą z nich korzystać. Kto ma uprawnienie do strony wtyczki, widzi przycisk **Administracja**,
a w nim tylko strony swoich wtyczek. Opis techniczny: [WTYCZKI.md](../WTYCZKI.md).

Link do obiektu na mapie: `?p=<projekt>&obiekt=<schemat.tabela>:<klucz>` otwiera projekt, przybliża obiekt
i otwiera jego formularz (np. z wtyczki: „Pokaż na mapie”). Adres w przeglądarce po takim przejściu można
skopiować i wysłać.
