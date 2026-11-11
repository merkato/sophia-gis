# Uprawnienia i zakres danych

Uprawnienia w Sophii mają trzy piętra:

| Piętro | Kto ustawia | Co ustala |
|---|---|---|
| **Serwer** | administrator (panel → Użytkownicy) | **administrator** — wszystko; **autor projektów** — publikuje projekty z QGIS (Fia) |
| **Projekt** | administrator (panel → Projekty → Grupy i zakres) | grupa: rola (podgląd / edycja / zarządzanie), prawo do **zdjęć** i **dokumentów** |
| **Zakres danych** | autor w **Fii** (reguły) + administrator (kody dla grup) | które obiekty grupa widzi i edytuje: cały obszar albo wybrane obszary |

Jeden filtr zakresu działa wszędzie: w formularzach i listach, na **obrazie mapy**, w identyfikacji,
wydrukach i raportach, w zdjęciach i dokumentach, w słownikach (listy wyboru) i przy pobieraniu
zdjęć do QGIS przez Fię.

## Serwer

- **Administrator** widzi i edytuje wszystko, zarządza użytkownikami, grupami i projektami.
- **Autor projektów** (zaznaczenie „Autor projektów (publikacja z QGIS)” przy użytkowniku) publikuje
  projekty z QGIS przez Fię bez pełnych praw administratora. Projekt opublikowany przez autora jest
  jego własnością: autor ma w nim pełny dostęp, może go aktualizować, a cudzego projektu o tym samym
  identyfikatorze nie nadpisze. Dostęp dla innych grup nadaje administrator.

## Projekt

*Panel → Projekty → **Grupy i zakres…***. Dla każdej grupy:

- **rola**: *podgląd* (tylko oglądanie), *edycja* (dodawanie, zmiana, usuwanie obiektów warstw
  edytowalnych w Fii), *zarządzanie*;
- **zdjęcia** i **dokumenty** — prawo dodawania zdjęć (także z aparatu) i plików. Domyślnie włączone.
  Bez nich grupa ogląda zdjęcia i dokumenty, ale nie widzi przycisków wysyłania;
- **zakres**: *cały obszar* albo *wybrane* kody obszarów (gdy projekt ma wymiar zakresu — niżej).

Użytkownik w kilku grupach dostaje sumę uprawnień: najwyższą rolę, prawa z którejkolwiek grupy
i wszystkie kody obszarów. Grupa z „całym obszarem” znosi ograniczenie zakresu.

Projekt **publiczny** ogląda każdy, także bez logowania i bez ograniczeń zakresu — nie ustawiaj
publicznego dostępu dla danych, które mają być dzielone na obszary.

## Zakres danych — konfiguracja w Fii

*Web → Fia → zakładka **Zakres danych***.

### 1. Wymiar zakresu

| Ustawienie | Przykład |
|---|---|
| **Nazwa** | Oddział terenowy |
| **Warstwa granic obszarów** | `oddzialy` (poligony) |
| **Pole z kodem obszaru** | `kod` (wartości `od01`, `od02`…) |

Warstwa granic musi być w PostGIS, w tej samej bazie co warstwy z regułą przestrzenną. Kody z tego
pola administrator wybiera potem dla grup.

### 2. Reguła dla każdej warstwy

| Reguła | Kiedy | Jak działa |
|---|---|---|
| **automatycznie** | domyślnie | warstwa z geometrią → przestrzennie; tabela bez geometrii będąca dzieckiem w relacji → przez relację; pozostałe → bez ograniczeń |
| **przestrzennie** | działki, drzewa, obszary wniosków | **podgląd**: obiekt przecina obszar; **edycja**: punkt wewnątrz obiektu leży w obszarze. Obiekt na granicy jest widoczny w obu oddziałach, ale edytuje go jeden |
| **atrybut** | tabela decyzji z polem `oddzial` | pole ma jeden z kodów użytkownika. Przy jednym kodzie Sophia sama wpisuje go w nowym rekordzie |
| **przez relację** | oględziny, zdjęcia, dokumenty | rekord widać, gdy widać obiekt nadrzędny (relacja z projektu QGIS; do trzech poziomów) |
| **bez ograniczeń** | słowniki, sama warstwa granic | wszyscy z dostępem do projektu widzą całość |

Kolumna **Uwagi** pokazuje, jak reguła „automatycznie” została rozstrzygnięta, i ostrzega, gdy tabela
bez geometrii byłaby widoczna w całości.

Zapisz konfigurację i opublikuj projekt.

## Przykład: urząd z oddziałami terenowymi

Fikcyjny **Urząd Ochrony Zieleni Województwa Przykładowego** wydaje zezwolenia na usunięcie drzew.
Wnioski rozpatrują w **pierwszej instancji** oddziały terenowe (Oddział Północ — kod `od01`, Oddział
Południe — `od02`), a odwołania w **drugiej instancji** centrala urzędu. Jedna sprawa może mieć kilka
decyzji: decyzję oddziału, decyzję centrali po odwołaniu, ponowną decyzję oddziału po uchyleniu.

Projekt QGIS:

- warstwy z geometrią: **działki**, **drzewa** (punkty), **obszary wniosków** — reguła *przestrzennie*,
- **decyzje** (tabela bez geometrii; pola `sprawa`, `instancja` = I / II, `oddzial` = `od01`, `od02`…)
  — reguła *atrybut*, pole `oddzial` (oddział, w którym toczy się sprawa),
- **oględziny terenowe** (tabela bez geometrii, relacja z obszarem wniosku; zdjęcia i protokoły
  w tabelach powiązanych) — reguła *przez relację*,
- słowniki (gatunki drzew, rodzaje rozstrzygnięć) — *bez ograniczeń*,
- wymiar zakresu: warstwa **oddzialy**, pole `kod`.

Grupy w panelu (*Projekty → Grupy i zakres*):

| Grupa | Rola | Zakres | Kto |
|---|---|---|---|
| Centrala – II instancja | edycja | cały obszar | pracownicy rozpatrujący odwołania |
| Centrala – podgląd | podgląd | cały obszar | kierownictwo, kontrola |
| Oddział Północ | edycja | `od01` | inspektorzy oddziału Północ |
| Oddział Południe | edycja | `od02` | inspektorzy oddziału Południe |

Efekt:

- centrala widzi wszystkie sprawy i decyzje obu instancji; grupa II instancji je edytuje, grupa
  podglądu tylko ogląda,
- inspektor oddziału Północ widzi na mapie, w formularzach i w wydrukach tylko działki, drzewa
  i obszary wniosków w granicach swojego oddziału, tylko decyzje z `oddzial = od01` (także decyzje
  centrali w sprawach z jego oddziału, jeśli mają ten kod) i tylko oględziny ze zdjęciami
  i protokołami przy obiektach ze swojego obszaru,
- próba przesunięcia obiektu poza swój oddział albo wpisania cudzego kodu jest odrzucana
  („Obiekt musi leżeć w Twoim obszarze”, „Pole „oddzial” musi mieć jedną z wartości: od01”),
- na pasku narzędzi WebUI użytkownik widzi swój zakres, np. „Oddział terenowy: od01”.

## Dobrze wiedzieć

- Zakres sprawdza serwer — nie da się go obejść z przeglądarki ani zapytaniem do usługi mapy.
- Mapa: warstwy wektorowe są filtrowane w QGIS Server (wtyczka `sophia_filter`). Rastry i podkłady
  nie są dzielone na obszary.
- Dawne „zasięgi” (narysowane obszary przypisane użytkownikom) zastąpił zakres danych w projekcie.
