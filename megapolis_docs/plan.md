# Megapolis – narzędzie wspierania decyzji o związkach aglomeracyjnych

Prototyp poglądowy dla całej Polski. Ma pokazywać rozwiązanie, ale **każda liczba jest policzona z prawdziwych danych** (`dataset/*.parquet`) i opisana: źródło, okres, pokrycie, niepewność. Żadnych mocków w wynikach.

## 1. Problem i decyzja

**Problem:** część miast i gmin traci funkcje społeczno-gospodarcze (mieszkańcy robią zakupy i korzystają z usług gdzie indziej). Wzmocnić je można przez współpracę w ramach związków aglomeracyjnych, ale trzeba wiedzieć, **z kim** i **czego im brakuje**.

**Decyzje, które narzędzie wspiera:**
1. Które gminy tracą funkcje i w jakich kategoriach (żywność, zdrowie, paliwa, gastronomia)?
2. Do czego faktycznie należą funkcjonalnie (jakie regiony tworzą przepływy mieszkańców)?
3. Z którymi gminami warto tworzyć związek i jaki byłby zasięg oraz samowystarczalność po połączeniu?

**Użytkownik:** samorząd, planista regionalny, analityk. Wynik to ranking i scenariusz z podaną niepewnością, nie tylko wykres.

**Czego narzędzie NIE twierdzi:** że połączenie gmin da określony skutek (mamy korelacje zachowań płatniczych, nie eksperyment). Pokazujemy, **gdzie związki funkcjonalne już istnieją** i jaki jest potencjał.

## 2. Fakty o danych, na których opieramy plan

| Fakt | Wartość | Źródło |
|---|---|---|
| Sample to **losowe 20% kart z pełną historią** | Dla 1% kart (`hash(card)%100=0`): full 97 343 karty / 15,22 mln transakcji, sample 19 423 karty / 3,07 mln; każda karta ze sample ma w full identyczną liczbę transakcji i te same daty | test próbki |
| Skala sample → full | ≈ ×4,96 | test próbki |
| Wskaźniki na kartę (samowystarczalność, odpływ) na sample | Nieobciążone (karta jest kompletna); większy szum dla małych gmin | wniosek |
| Jednostką niezależną jest **karta**, więc niepewność liczymy bootstrapem po kartach | – | wniosek |
| Kwoty | Waluta fikcyjna – tylko porównania względne | słownik |
| `pstl_cd_enr`/`lau_enr`/`fua_enr` | Szacowane miejsce stałego przebywania karty (zmienne w czasie: modalny kod zmienia się między kolejnymi miesiącami w 39% przypadków). **Puste od 2026-02-28 do 2026-03-30 i od 2026-04-30 do 2026-06-30** | słownik + testy |
| Zgodność modalnego `pstl_cd_enr` z kodem sprzedawcy przy zakupach codziennych | 55,6% dokładnie, 77,5% do prefiksu 3 cyfr | test |
| `lau_enr` vs nazwa gminy z GeoJSON | pasuje w 95,9% (Domestic); niepasujące to zagraniczne LAU | test |
| `mrch_postal_code` | Braki 3–8%; 95% da się znormalizować do `NN-NNN`; ok. 90% trafia do kodu z GeoJSON | test |
| `mrch_city_nm_raw` | Brudne (`WARSAW` ≠ `WARSZAWA`) – tylko kod pocztowy | test |
| GeoJSON kodów | 30 479 poligonów, 19 091 kodów, 2 232 nazwy gmin, **brak TERYT/powiatu**; 393 kody należą do >1 gminy | analiza |
| `fua_enr` | Oficjalne obszary funkcjonalne przypisane do karty – **wbudowana prawda odniesienia** do walidacji regionów | słownik |

### Wstępny sygnał (prowizoryczne mapowanie kod→gmina, wycinek 1% kart, zakupy codzienne; do potwierdzenia)
| Gmina domowa | Główny cel poza gminą (udział zakupów) |
|---|---|
| Skawina | Kraków 53% |
| Zabierzów | Kraków 50% |
| Wieliczka | Kraków 35% |
| Łomianki | Warszawa 40% |
| Tarnów | Rzeszów 17% (samowystarczalność ok. 58%) |

Ostrzeżenie: przy tym mapowaniu Nowy Sącz i Łomianki miały samowystarczalność 0% – to **artefakt mapowania kod→gmina**, nie wynik. Pokazuje, że jakość geografii decyduje o wiarygodności.

## 3. Trzy filary (rdzeń narzędzia)

### Filar 1 – Diagnoza: samowystarczalność i utrata funkcji
- **Samowystarczalność gminy** = udział zakupów codziennych (spożywcze, apteki, paliwa, piekarnie) mieszkańców zrobionych w gminie domowej. Liczona z `card_home` (gmina domowa karty) i `mrch_postal_code` (gmina zakupu).
- **Niedobór funkcji** w kategorii c: samowystarczalność gminy w c względem gmin z tej samej klasy wielkości (benchmark rówieśników, z-score). Rozszerzenie: model grawitacyjny (patrz niżej).
- **Niepewność:** bootstrap po kartach (np. 200 prób) → przedziały ufności; poniżej progu liczby kart „za mało danych”.
- **Kontrola wielkości:** duże miasta mają wysoką samowystarczalność z natury – porównujemy z rówieśnikami, nie z całym krajem. Dane o populacji z GUS (zewnętrzne).
- Wynik: ranking gmin „tracących funkcje” z CI i listą brakujących kategorii oraz miejsc, dokąd uciekają wydatki.

### Filar 2 – Regiony funkcjonalne z przepływów
- Graf skierowany gmina domowa → gmina zakupu (waga: liczba transakcji lub kart).
- Klasteryzacja grafu (Louvain/Leiden) → regiony funkcjonalne; opcjonalnie odległość jako regularyzacja.
- **Walidacja względem `fua_enr`:** zgodność klastrów z oficjalnymi FUA (ARI/NMI) na gminach powyżej progu; stabilność między połowami okresu i bootstrapami po kartach.
- Wynik: mapa regionów funkcjonalnych, gminy „na styku” (silne przepływy do dwóch ośrodków), różnice względem oficjalnych FUA.

### Filar 3 – Partnerzy i symulator związku
- **Ranking partnerów** dla gminy i: wynik ważony z jawnymi, edytowalnymi wagami:
  - siła obustronnego przepływu (i↔j),
  - bliskość (odległość centroidów),
  - komplementarność: gdzie i ma niedobór, a j jest silna (Σ_c niedobór_i,c × siła_j,c).
  - Analiza wrażliwości na wagi (jak zmienia się ranking).
- **Symulator:** dla zestawu 2–5 gmin: samowystarczalność zestawu (przepływy wewnętrzne / zakupy mieszkańców), zasięg (karty, ludność), pokrycie kategorii, przed/po; udział gości zagranicznych jako dodatkowy popyt.
- **Walidacja rankingu (back-test):** czy ranking odtwarza znane pary z jednego FUA (precision@k); czy ranking z pierwszej połowy okresu przewiduje przepływy w drugiej.
- Wynik: „dla gminy X najlepsi partnerzy to …, po połączeniu samowystarczalność rośnie z A% do B% (CI)”. To opis potencjału, nie prognoza skutku.

## 4. Warstwa wspierająca (statystyki opisowe)
- **Goście z kart zagranicznych** (nie „turyści”): udział, kraje pochodzenia, średni rachunek, region pochodzenia (kod pocztowy kupującego, karty Intra) → dodatkowy popyt, który zestaw gmin może wykorzystać.
- Sezonowość i heatmapa godzin (bez `000000`, czas PL).
- Kanały płatności, e-commerce (`cp_flag=0`), segment karty (bez kart firmowych CO/BZ/GV).
- Wyniki referencyjne z danych (wycinek 1%, karty zagraniczne u polskich sprzedawców): Świnoujście 26,9%, Zakopane 18,0% (Słowacja 23%), Zgorzelec 17,4%, Sopot 14,7%, Cieszyn 10,8% (Czechy 95%), Kraków 8,3%, Warszawa 4,8%, Tarnów 0,7% (mała próba). Służą jako testy regresji, nie oczekiwania. Kraj gości zależy od regionu: Ukraina pierwsza w 23 z 51 większych miast, UK w 8, Niemcy w 4.

## 5. Zasady prototypu
1. Liczby tylko z danych; przy każdym widoku: źródło (sample/full), okres, liczba kart i transakcji, udział bez lokalizacji.
2. Udziały i rankingi z przedziałami ufności; próg minimalny (start: 30 kart i 1000 transakcji) → „za mało danych”.
3. Liczby bezwzględne z etykietą „sample (20% kart)”, opcjonalnie ×4,96 jako „szacunek”.
4. Zakładka „Jak czytać dane i metodę”: fikcyjna waluta, okna bez `_enr`, `card_home` jako szacunek, sample vs full, mapowanie kod→gmina, co narzędzie nie twierdzi.
5. Wagi i progi widoczne i edytowalne, bez ukrytych parametrów.

## 6. Dane zewnętrzne (brakujący wkład)
| Dane | Po co | Uwagi |
|---|---|---|
| Liczba mieszkańców gmin (GUS) | Klasy wielkości, benchmark rówieśników, normalizacja | Klucz: TERYT lub nazwa+powiat |
| Granice gmin z TERYT (np. PRG) | Jednoznaczna tożsamość gmin (obecny GeoJSON skleja ok. 245 gmin o wspólnych nazwach) | Alternatywa: obecny GeoJSON + rozstrzygnięcie po położeniu |
| Centroidy i odległości | Bliskość w rankingu, model grawitacyjny | Z geometrii gmin |

Mapowanie kod pocztowy → gmina: zamiast jednej gminy na kod użyć udziałów powierzchni (393 kody należą do >1 gminy), co ogranicza błąd u granic; zastosowanie opisujemy w metodologii.

## 7. Architektura

```
build_marts.py  ->  dataset/marts/*.parquet   (jednorazowo; --source sample|full)
models/         ->  diagnosis.py, regions.py, partners.py (wejście: marts, wyjście: tabele wyników)
app/            ->  queries.py (DuckDB na marts), map_builder.py, panele Plotly
streamlit_app.py
```

| Tabela | Ziarno | Miary |
|---|---|---|
| `postal_gmina` | kod → gmina (z udziałami powierzchni) | mapowanie |
| `card_home` | karta → gmina/kod/FUA domowy, pewność (udział modalnego), liczba wierszy z kodem | okno z danymi |
| `flows` | gmina domowa × gmina zakupu × kategoria (codzienne/inne, top kategorie) × miesiąc | n_tx, kwota, n_kart |
| `flows_boot` | gmina domowa × gmina zakupu × próba bootstrapowa | n_tx (do CI) |
| `m_postal_month` | kod sprzedawcy × miesiąc × `issr_jurn` × kraj wydawcy (top 30 + INNE) × segment karty × `cp_flag` | n_tx, kwota |
| `m_postal_time` | kod × dzień tygodnia × godzina × gość/lokalny | n_tx, kwota |
| `gmina_ref` | gmina: populacja (GUS), centroid, klasa wielkości | atrybuty |
| tabele wyników modeli | `diagnosis`, `regions`, `partners` | wynik + CI |

`card_home` liczony z okresu z danymi (2025-01-01…2026-02-27, dodatkowo 2026-03-31…04-29) i przypisany do wszystkich transakcji karty.

## 8. Widoki aplikacji
| # | Widok | Filar |
|---|---|---|
| 1 | Mapa: wskaźnik do wyboru (samowystarczalność, niedobór funkcji, odpływ), łuki przepływów dla wybranej gminy | 1 |
| 2 | Karta gminy: diagnoza z CI, benchmark rówieśników, niedobory wg kategorii, dokąd uciekają wydatki | 1 |
| 3 | Regiony funkcjonalne vs oficjalne FUA, miara zgodności, gminy na styku | 2 |
| 4 | Partnerzy i symulator związku (przed/po, wagi edytowalne) | 3 |
| 5 | Porównanie gmin/obszarów (także z innym regionem Polski) | 1 |
| 6 | Goście i sezonowość jako dodatkowy popyt | wsparcie |
| 7 | Metodologia i ograniczenia | – |
| 8 | Rozszerzenie: model grawitacyjny (PPML), klasteryzacja typów gmin, anomalie | 1 |

## 9. Testy realności i jakości (z danych, bez założeń o wynikach)
- **T1 sumy:** suma po gminach + „bez lokalizacji” = suma krajowa w każdym miesiącu.
- **T2 sample vs full (rozkład):** udział miesięcy w sample ≈ w `overview_datasprint_full_data.json` (±1 pp).
- **T3 sample vs full (gminy):** dla 30 największych gmin wskaźniki ze sample mieszczą się w CI wskaźników z full.
- **T4 stabilność:** wskaźniki gmin z miesięcy parzystych i nieparzystych korelują (Spearman ≥ 0,9 powyżej progu).
- **T5 pokrycie:** udział transakcji bez lokalizacji raportowany, ≤ ok. 10%.
- **T6 kod domowy:** zgodność z kodem sprzedawcy przy zakupach codziennych ≥ 55% dokładnie / ≥ 77% do prefiksu 3 cyfr (regresja zmierzonych wartości).
- **T7 regresja wyników referencyjnych** z pkt 4.
- **T8 regiony:** ARI/NMI względem `fua_enr` raportowane, stabilne między połowami okresu i bootstrapami.
- **T9 partnerzy:** precision@k odtwarzania par z jednego FUA; back-test przepływów z drugiej połowy okresu.
- **T10 kontrola mapowania:** brak gmin z samowystarczalnością równą 0% wynikającą z błędu mapowania (kontrola przykładów: Nowy Sącz, Łomianki).

## 10. Ograniczenia (do pokazania w aplikacji)
- Karty to nie ludzie: widzimy wydatki Visa, bez populacji (dodajemy GUS), bez gotówki i innych sieci.
- 18 miesięcy (z kodem domowym ok. 14) – stan i porównania, nie długoterminowe trendy „tracenia funkcji”.
- Kod domowy karty jest szacunkiem dostawcy i zmienia się w czasie.
- Sample: 20% kart; mniejsze gminy mają szeroki CI (po przeliczeniu na full wąski).
- Korelacja, nie skutek: rekomendacje pokazują istniejące związki, nie efekt połączenia.
- Kwoty w walucie fikcyjnej.

## 11. Podział na 4 osoby

Kontrakt pierwszego dnia: schematy marts, klucz gminy, format tabel wyników modeli.

| Osoba | Zadania | Filar / widoki |
|---|---|---|
| **1 – Dane i geo** | `build_marts.py` (strona sprzedawcy), normalizacja kodów, `postal_gmina` z udziałami, import GUS, centroidy, T1, T2, T5, T10 | fundament; 6 |
| **2 – Diagnoza** | `card_home`, `flows`, `flows_boot`, samowystarczalność, benchmark rówieśników, niedobory funkcji, CI, T4, T6 | filar 1; 1, 2, 5 |
| **3 – Modele** | Klasteryzacja grafu + walidacja względem `fua_enr`, ranking partnerów, symulator, back-test, (rozszerzenie: model grawitacyjny) | filary 2 i 3; 3, 4 |
| **4 – Aplikacja** | Streamlit: mapa, panele Plotly, edycja wag, zakładka metodologii, T3, T7, README i demo | całość; 7 |

## 12. Kolejność
1. **Ustalenia (0,5 dnia):** klucz gminy (TERYT vs nazwa+powiat), źródło GUS, kontrakt schematów, próg minimalny.
2. **Fundament:** marts na sample, `postal_gmina`, `card_home`, `flows`; szkielet aplikacji na małym pliku.
3. **Filar 1** (diagnoza) + widoki 1, 2 → pierwszy działający prototyp decyzyjny.
4. **Filar 2** (regiony) + widok 3, walidacja względem `fua_enr`.
5. **Filar 3** (partnerzy, symulator) + widok 4, back-test.
6. Warstwa wspierająca (widok 6), porównanie (5).
7. Przeliczenie marts z full, T1–T10, ponowna walidacja, metodologia, README, demo.
8. Rozszerzenia (widok 8), jeśli starczy czasu.

**Wersja minimalna (gdy brakuje czasu):** filar 1 + filar 3 w uproszczeniu (ranking bez komplementarności), z widokami 1, 2, 4 i metodologią.

**Scenariusz demo:** wybieramy po policzeniu wyników – gmina z wysokim odpływem i wiarygodnym CI, dla której ranking wskazuje partnera z realnym przepływem; pokazujemy diagnozę, region funkcjonalny, ranking partnerów i symulację przed/po razem z niepewnością.

## 13. Decyzje otwarte
1. **Granice gmin:** TERYT (rekomendowane) vs obecny GeoJSON.
2. **Źródło i klucz danych GUS** (populacja gmin).
3. **Próg minimalny** (start: 30 kart, 1000 transakcji) i liczba prób bootstrapu.
4. **Waga początkowa** w rankingu partnerów (start: równe, do strojenia na back-teście).
5. **Skalowanie ×4,96:** surowe liczby sample z przełącznikiem „szacunek dla full” (rekomendacja).
6. **Kiedy przeliczamy full:** po ustabilizowaniu na sample (przebieg po 87 GB).

## 14. Poprawki do obecnego kodu (`app/`, `streamlit_app.py`)
- `get_stats_gmina` filtruje po `pstl_cd_enr` (kod kupującego) → zmienić na `mrch_postal_code` (znormalizowany do `NN-NNN`) dla widoków sprzedawcy; strona „mieszkańcy” z `card_home`.
- Zapytania po surowym parquet (minuty na klik) → zastąpić marts.
- Zapytania f-stringami → parametryzowane; konfiguracja DuckDB (limit pamięci, wątki, `temp_directory`) w jednym miejscu; ścieżka danych w konfiguracji (domyślnie sample).
- Klik mapy: właściwości klikniętego obiektu zamiast parsowania tooltipa.
- Losowy kolor gmin (i niestabilny `hash()`) → choropleta po wskaźniku; uproszczona geometria.
- Sprzątanie: `main.py`, pusty `scripts/`, niewykorzystany `charts.py` (base64 PNG) do zastąpienia Plotly.
