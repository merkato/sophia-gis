# Sophia — dokumentacja użytkownika

Dla osób, które **przygotowują projekty w QGIS** (autor projektu) i **pracują w przeglądarce**
(WebUI). Instalacja i utrzymanie serwera są opisane osobno, dla administratora: [SERVER.md](../SERVER.md).

## Konfiguracja projektu w QGIS

| Temat | Co opisuje |
|---|---|
| [Zdjęcia w obiektach](zdjecia.md) | pole „Załącznik” w tabeli albo tabela zdjęć w relacji, aparat w telefonie |

Zasady ogólne, wspólne dla wszystkich tematów:
- warstwy edytowalne w WebUI muszą pochodzić z **PostGIS**, z połączenia przez usługę `sophia`
  (`pg_service.conf`), i mieć klucz główny,
- formularz w WebUI powstaje z ustawień *Właściwości warstwy → Formularz atrybutów*: aliasy,
  widżety (lista wartości, odwołanie do relacji, data, pole wyboru, załącznik…), pola ukryte
  i tylko do odczytu, pola wymagane,
- relacje (*Projekt → Właściwości → Relacje*) dają w formularzu zakładki **Powiązane** i **Zdjęcia**,
- przed publikacją sprawdź zakładkę **Diagnostyka** w Fii,
- hasło do Sophii Fia trzyma w **menedżerze uwierzytelniania QGIS** (zakładka **Serwer**,
  „Zapamiętaj…”). Służy do publikacji i do pobierania zdjęć.

## Praca w przeglądarce

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
| żółty ołówek + lista | **Włącz / zakończ edycję** i wybór warstwy edycyjnej | Przełącz edycję |
| przerywany prostokąt ze strzałką | **Zaznacz obiekt** warstwy edycyjnej | Zaznacz obiekty |
| zielony punkt / linia / poligon z gwiazdką | **Dodaj obiekt** — ikona zależy od typu geometrii warstwy | Dodaj obiekt punktowy / liniowy / poligonowy |
| tabela z zielonym plusem | **Dodaj rekord** — dla tabel bez geometrii | Dodaj rekord |
| poligon z czerwonym węzłem | **Narzędzie wierzchołków** — przeciąganie wierzchołków; zwykłe kliknięcie otwiera obiekt | Narzędzie wierzchołków |
| czerwony kosz | **Usuń zaznaczony obiekt** (z potwierdzeniem) | Usuń zaznaczone |

### Edycja
- Warstwę do edycji wybierasz na pasku narzędzi (lista obok ołówka) albo ołówkiem w drzewie warstw.
- Po zapisie nowego obiektu narzędzie wraca do **Zaznacz obiekt**.
- Tabele bez geometrii (słowniki, tabele nadrzędne) mają listę rekordów w panelu bocznym zamiast mapy.
- Na telefonie panel warstw jest domyślnie schowany i otwiera się ikoną warstw.
