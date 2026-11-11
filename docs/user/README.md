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

### Edycja
- Warstwę do edycji wybierasz ołówkiem w drzewie warstw.
- **Wybierz** — kliknięcie obiektu otwiera go w formularzu.
- **Rysuj** — nowy obiekt. Po zapisie narzędzie wraca do **Wybierz**.
- **Zmień geometrię** — przeciąganie wierzchołków. Zwykłe kliknięcie otwiera obiekt w formularzu.
- Tabele bez geometrii (słowniki, tabele nadrzędne) mają listę rekordów zamiast mapy.
