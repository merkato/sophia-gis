# Zdjęcia w obiektach

Sophia pozwala dołączać zdjęcia do obiektów — z dysku, z galerii telefonu albo **wprost z aparatu**
telefonu lub tabletu. Konfigurację robisz w QGIS (projekt i baza), a Fia publikuje ją na serwer.
Są dwa warianty i możesz ich używać jednocześnie, nawet w tym samym projekcie.

| | Wariant A: pole w tabeli obiektu | Wariant B: tabela zdjęć w relacji |
|---|---|---|
| Ile zdjęć na obiekt | jedno (na każde pole) | dowolnie wiele |
| Co dodajesz w bazie | kolumnę tekstową | osobną tabelę z kluczem obcym |
| Gdzie w formularzu WebUI | w zakładce **Atrybuty**, jak inne pola | zakładka **Zdjęcia** z galerią |
| Opis, data, autor zdjęcia | nie | tak, jako zwykłe pola tabeli zdjęć |
| Miejsce zrobienia zdjęcia | nie | punkt z GPS telefonu, jeśli tabela ma geometrię |
| Kiedy wybrać | „zdjęcie poglądowe”, np. tabliczka, widok ogólny | dokumentacja terenowa, wiele ujęć, historia |

W obu wariantach w bazie zapisywana jest **ścieżka względna** do pliku, np.
`zdjecia/obiekty/2026-11/3f2a….jpg`, a sam plik leży na serwerze w katalogu projektu
(szczegóły w sekcji [Gdzie są pliki](#gdzie-są-pliki-i-jak-zobaczyć-zdjęcia-w-qgis)).

---

## Wariant A — pole „Załącznik” w tabeli obiektu

### 1. Kolumna w bazie

Dodaj kolumnę tekstową, np. w QGIS: *Przeglądarka → baza → tabela → prawy klik → Zarządzanie polami*,
albo w SQL (np. Menedżer BD → Okno SQL):

```sql
ALTER TABLE dane.obiekty ADD COLUMN zdjecie text;
```

### 2. Widżet w QGIS

*Właściwości warstwy → **Formularz atrybutów** (Attributes Form) → pole `zdjecie`*:

1. **Typ widżetu:** **Załącznik** (Attachment).
2. **Ścieżka → Zapisz ścieżkę jako:** **Ścieżka względna do projektu** (Relative to project path).
   To jest ważne: przy ścieżce bezwzględnej (`C:\…`) serwer nie znajdzie pliku, a Fia pokaże ostrzeżenie.
3. **Tryb zapisu:** **Ścieżki plików** (File paths).
4. **Zintegrowana przeglądarka dokumentów → Typ:** **Obraz** (Image). Po tym Sophia rozpoznaje, że to
   pole na zdjęcie, i pokazuje miniaturę oraz przyciski aparatu.
   - Zamiast tego wystarczy filtr plików z rozszerzeniami obrazów, np. `Obrazy (*.jpg *.jpeg *.png *.heic)`.
5. Opcjonalnie **Alias** (np. „Zdjęcie”). Sophia pokaże go jako etykietę pola.

### 3. Publikacja

Zapisz projekt i opublikuj go przez **Fię**. Warstwa musi być zaznaczona jako edytowalna.
Zakładka **Diagnostyka** sprawdza pola „Załącznik”:
- **błąd**, gdy pole nie jest tekstowe,
- **ostrzeżenie**, gdy ścieżka nie jest względna do projektu,
- **informacja**, gdy brak podglądu obrazu (wtedy WebUI pokaże zwykły plik, bez aparatu).

### Jak to wygląda w WebUI

W formularzu obiektu pole pokazuje miniaturę zdjęcia oraz przyciski:
- **📷 Aparat** (tylko na telefonie i tablecie) — otwiera aparat, zdjęcie trafia od razu do pola,
- **🖼 Galeria / Wybierz zdjęcie** — wybór pliku z galerii lub dysku,
- **Usuń zdjęcie** — czyści pole.

Zdjęcie jest wysyłane od razu, ale **przypisane do obiektu dopiero po kliknięciu Zapisz**.
Kliknięcie miniatury otwiera zdjęcie w pełnym rozmiarze.

---

## Wariant B — osobna tabela zdjęć w relacji

### 1. Tabela w bazie

Przykład dla tabeli obiektów `dane.obiekty` z kluczem `fid`:

```sql
CREATE TABLE dane.obiekty_zdjecia (
    fid          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    obiekt_fid   integer NOT NULL REFERENCES dane.obiekty (fid) ON DELETE CASCADE,
    plik         text NOT NULL,              -- ścieżka zdjęcia (widżet Załącznik)
    opis         text,
    dodano       timestamptz NOT NULL DEFAULT now(),
    geom         geometry(Point, 2180)       -- opcjonalnie: miejsce zrobienia zdjęcia
);
CREATE INDEX ON dane.obiekty_zdjecia (obiekt_fid);
```

- Kolumna `geom` jest **opcjonalna**. Jeśli jest (typ punktowy), Sophia wpisze w nią położenie z GPS
  zdjęcia, a gdy zdjęcie nie ma GPS — punkt leżący na obiekcie nadrzędnym. Bez `geom` tabela jest
  zwykłą tabelą bez geometrii.
- Pozostałe kolumny bez wartości domyślnej nie mogą być `NOT NULL` — WebUI przy dodawaniu zdjęcia
  wypełnia tylko klucz obcy, ścieżkę i geometrię. Opis i inne pola uzupełnisz w rekordzie zdjęcia.
- `ON DELETE CASCADE` (albo relacja typu *Kompozycja*, niżej) usuwa rekordy zdjęć razem z obiektem.

### 2. Warstwa i widżety w QGIS

1. Dodaj tabelę `obiekty_zdjecia` do projektu (połączenie przez usługę `sophia`, jak inne warstwy).
2. W *Formularzu atrybutów* tej warstwy ustaw pole `plik` dokładnie jak w wariancie A
   (**Załącznik**, ścieżka względna do projektu, przeglądarka **Obraz**).
3. Pole `obiekt_fid`: widżet **Odwołanie do relacji** (Relation Reference) — po utworzeniu relacji
   (krok 3). Dzięki temu w WebUI rekord zdjęcia pokazuje nazwę obiektu zamiast numeru.
4. Pole `dodano`: widżet **Data/czas** (Date/Time), bez zaznaczenia „Edytowalne”. Po tym polu galeria
   grupuje zdjęcia w **wizytacje** (jeden dzień = jedna grupa). Nie ustawiaj go jako **Ukryte** —
   ukrytych pól WebUI nie odczytuje.
   - Sophia bierze pierwsze pole z widżetem Data/czas, a gdy takiego nie ma — pole o nazwie
     `data_wizytacji`, `wizytacja`, `data_zdjecia`, `data`, `dodano` lub `created_at`.
   - Bez pola daty galeria pokazuje po prostu wszystkie zdjęcia.
5. Pole `fid` można ukryć (widżet **Ukryty**).

### 3. Relacja w projekcie

*Projekt → Właściwości → **Relacje** → Dodaj relację*:

| Ustawienie | Wartość |
|---|---|
| Nazwa | np. „Zdjęcia” — taki nagłówek pokaże galeria |
| Warstwa nadrzędna (Referenced layer) | `obiekty`, pole `fid` |
| Warstwa podrzędna (Referencing layer) | `obiekty_zdjecia`, pole `obiekt_fid` |
| Siła relacji | **Kompozycja**, jeśli usunięcie obiektu ma usuwać zdjęcia; inaczej **Powiązanie** |

### 4. Publikacja

Opublikuj projekt przez Fię. Edytowalne muszą być **obie** warstwy:
- tabela zdjęć — żeby dodawać i usuwać zdjęcia,
- tabela obiektów — jeśli chcesz zmieniać atrybuty obiektów (do samego oglądania galerii nie musi).

### Jak to wygląda w WebUI

Formularz obiektu ma zakładkę **Zdjęcia (liczba)** z galerią miniatur pogrupowaną w wizytacje,
np. „Wizytacja 11.11.2026 (5 zdjęć)”, najnowsze na górze:
- **📷 Aparat** (telefon, tablet) — każde naciśnięcie to jedno zdjęcie, od razu zapisane jako nowy
  rekord. W terenie robisz serię: Aparat → zdjęcie → Aparat → kolejne ujęcie…,
- **🖼 Dodaj zdjęcia** — wybór **kilku zdjęć naraz** z galerii telefonu lub dysku; każde staje się
  osobnym rekordem,
- kliknięcie miniatury otwiera podgląd na cały ekran: strzałki lub przesunięcie palcem przechodzą
  do kolejnych zdjęć, **Rekord** otwiera rekord zdjęcia (np. żeby dopisać opis), **Usuń** usuwa rekord.

Zakładka pojawia się po zapisaniu obiektu: do nowego, jeszcze niezapisanego obiektu nie ma jak
przypiąć rekordów zdjęć.

---

## Co robi serwer ze zdjęciem

- obraca zdjęcie zgodnie z orientacją telefonu (EXIF),
- zmniejsza je tak, by dłuższy bok miał najwyżej **2560 px**, i zapisuje jako **JPEG**
  (zdjęcia z iPhone'a w formacie HEIC też są przyjmowane),
- **zachowuje** w pliku datę zrobienia i współrzędne GPS (EXIF),
- przygotowuje miniaturę do galerii.

Limit wielkości wysyłanego pliku: 40 MB.

## Gdzie są pliki i jak zobaczyć zdjęcia w QGIS

Zdjęcia wysłane z WebUI leżą na serwerze w katalogu uploadów projektu:

```
/opt/sophia/data/uploads/<slug-projektu>/zdjecia/<tabela>/<rok-miesiąc>/<plik>.jpg
```

Zdjęcia **dodajesz tylko przez WebUI** (przeglądarka na telefonie, tablecie albo komputerze).
QGIS Desktop służy do ich **oglądania**.

### Pobieranie zdjęć do QGIS (Fia)

Ścieżka w bazie (`zdjecia/…`) jest względna, więc QGIS pokaże zdjęcie, jeśli w **folderze projektu
na Twoim komputerze** będzie ten sam podkatalog `zdjecia`. Pobiera je Fia:

1. *Web → Fia → Fia – konfiguracja i publikacja…*, zakładka **Serwer**.
2. Wpisz adres portalu, swój login i hasło. Zaznacz **Zapamiętaj w menedżerze uwierzytelniania QGIS**.
3. Kliknij **Pobierz zdjęcia z serwera do folderu projektu**.

Później wystarczy *Web → Fia → **Fia – pobierz zdjęcia z Sophii*** — bez otwierania okna.
Pobierane są tylko pliki nowe lub zmienione, więc kolejne pobrania trwają krótko.
Po pobraniu zdjęcia są dostępne także bez internetu.

**Kto widzi które zdjęcia.** Zdjęcie widzi każdy, kto może oglądać **obiekt**, do którego jest
dowiązane — tak samo w WebUI, jak przy pobieraniu do QGIS:
- dostęp do projektu (projekt publiczny albo grupa z rolą w projekcie),
- uprawnienie do warstwy (także nadpisania uprawnień warstw dla grupy),
- **zasięg przestrzenny** użytkownika: obiekty poza zasięgiem i ich zdjęcia są niedostępne. W tabeli
  zdjęć bez geometrii (wariant B) decyduje położenie obiektu nadrzędnego z relacji.

**Hasło** jest przechowywane w **menedżerze uwierzytelniania QGIS** (*Ustawienia → Opcje →
Uwierzytelnianie*), czyli w zaszyfrowanej bazie QGIS chronionej hasłem głównym. Przy pierwszym
zapisie QGIS poprosi o ustawienie hasła głównego. Może je zapamiętać w Menedżerze poświadczeń Windows,
żeby nie pytać przy każdym uruchomieniu. Ten sam wpis służy do publikacji projektu przez Fię.

Na serwerze Sophia szuka pliku najpierw w katalogu uploadów, potem obok pliku projektu.

Kopia zapasowa serwera (`scripts/server/backup.sh`) obejmuje katalog uploadów.

## Dobre praktyki

- Kolumny ze ścieżką zawsze typu `text`.
- Usunięcie zdjęcia w WebUI (pola albo rekordu) **nie kasuje pliku** z serwera — plik zostaje jako
  zabezpieczenie przed pomyłką.
- Nie zmieniaj ręcznie nazw plików w katalogu uploadów — w bazie są zapisane pełne ścieżki.
- Zdjęcia zawierają współrzędne GPS. Pamiętaj o tym, udostępniając projekt publicznie — w projekcie
  publicznym zdjęcia widzi każdy odwiedzający.
