# Statystyki do analizy – lista i uwagi o jakości danych

Podstawa: profilowanie `dataset/datasprint_sample_data.parquet` (305 mln wierszy; polscy sprzedawcy: 260 mln).
Każda statystyka ma przypisaną decyzję, którą wspiera.

## Problemy z danymi do rozwiązania przed MVP

1. **Czym jest `pstl_cd_enr` (rozstrzygnięte, patrz „Wyniki weryfikacji”).** Według słownika (`docs/Dictionary_data_Visa.xlsx`) to **kod pocztowy przypisany do karty**; `lau_enr` to „~miejsce stałego przebywania posiadacza karty na podstawie wykonywanych transakcji” – czyli **szacunek wyliczony przez dostawcę danych, a nie adres z umowy**. Nie jest to lokalizacja sprzedawcy. Kody są w formacie kraju wydawcy (DE `21465`, UK `BH1 4HN`, CZ `735 81`, PL `86-100`). W tych samych kolumnach są `lau_enr`/`fua_enr` (gmina/obszar funkcjonalny kupującego). Wartość jest przypisana do karty na dany dzień (stała w obrębie dnia), zmienia się w czasie i **jest pusta w całych oknach czasowych** (problem 5).
   - **Do lokalizacji transakcji (gdzie kupiono)** używać `mrch_postal_code` / `mrch_city_nm_raw` (braki ok. 4,5%).
   - **Do pochodzenia kupującego (skąd jest)** używać `pstl_cd_enr` / `lau_enr` / `fua_enr`.
   - Pokrycie pochodzenia (w okresach z danymi, patrz problem 5): Domestic ~98,5% transakcji, **Intra ~74% transakcji** (turyści z UE – kod domowy do poziomu kodu pocztowego!), **Inter 0%** (tylko kraj wydawcy).
2. **Nie mieszać dwóch geografii** w jednym wskaźniku: zgodność `pstl_cd_enr` z `mrch_postal_code` to tylko ok. 34% (ludzie kupują blisko domu, ale nie zawsze).
3. **Godzina 00 to artefakt** (32 mln wierszy, 12%, średnia kwota 225; godziny 01–03 mają po kilkaset tys.). Analiza godzinowa bez godz. 00, z raportem ile odrzucono. Czas jest w GMT – przesunąć na czas polski.
4. **Kod domowy karty (`card_home`)** = najczęstszy `pstl_cd_enr` karty (najlepiej liczony w oknie czasowym, np. kwartał). Jest stabilny tylko częściowo: najczęstszy kod ma ≥80% transakcji u 47% kart, ≥50% u 76%; w obrębie miesiąca 86% kart ma jeden kod. Do każdego wskaźnika „mieszkańcy” dołączać **poziom pewności** (udział modalnego kodu) i filtrować np. ≥50%. Własna heurystyka (modalny kod z zakupów codziennych) służy tylko do walidacji.
5. **`pstl_cd_enr`/`lau_enr`/`fua_enr` są puste w całych oknach czasowych:** od 2026-02-28 do 2026-03-30 oraz od 2026-04-30 do 2026-06-30 (prawie 100% braków, także dla kart krajowych). Poza tym oknami braki to ok. 1,2% (Domestic, sprzedawca w PL) i ok. 26% (Intra). Wcześniejsze „19,6% braków” wynikało głównie z tych okien. Wskaźniki oparte na kodzie domowym liczyć z okresu z danymi (2025-01-01…2026-02-27, dodatkowo 2026-03-31…2026-04-29), a **wyznaczony kod domowy karty przypisać do wszystkich jej transakcji** – wtedy wskaźniki działają także dla miesięcy bez `_enr`.
6. **Karty firmowe** wyłączać po `prod_id_pltfrm_cd_vcis` (CN – konsument, CO – commercial, BZ – business, GV – government), a nie po `crd_typ_nm` (BUSINESS: średnia 517 vs 148 dla CLASSIC zaburza średnie). Kwoty: używać mediany i p95 (mediana 52, średnia 161).
7. **`cs_tran_amt` jest w walucie fikcyjnej** (przygotowanej na hackathon) – nie podawać „zł”, porównywać tylko względnie.

## A. Turyści i goście (po kliknięciu obszaru)
| Statystyka | Kolumny | Decyzja |
|---|---|---|
| Liczba transakcji i kwota od kart zagranicznych, udział w obrocie | `issr_jurn`, `issr_ctry_nm`, `cs_tran_amt` | Jak bardzo obszar żyje z turystyki |
| Kraje pochodzenia (top 10) | `issr_ctry_nm` | Do kogo kierować ofertę |
| **Region pochodzenia turysty** (kod pocztowy/gmina kupującego, np. niemiecki PLZ, brytyjski postcode) – tylko karty Intra (kod ma ok. 74% transakcji Intra w okresach z danymi) | `pstl_cd_enr`, `lau_enr`, `issr_ctry_nm` | Skąd dokładnie przyjeżdżają goście, gdzie prowadzić promocję |
| **Polacy za granicą:** karty PL użyte u sprzedawcy poza Polską (Intra/Inter), z kodem domowym | `issr_ctry_nm='POLAND'`, `mrch_ctry_nm`, `pstl_cd_enr` | Odpływ transgraniczny mieszkańców obszaru (Czechy, Słowacja, Niemcy) |
| Średni rachunek wg kraju | j.w. | Kogo opłaca się przyciągać (UA: 121, DE: 354, CZ: 320 – jednostki fikcyjne) |
| Turysta krajowy (karta PL, kod domowy poza obszarem) | `card_home` | Ruch z innych regionów |
| Udział kart premium wśród gości | `crd_typ_nm` | Segment zamożny |
| Sezonowość gości | `prch_mnth_id`, `myweek` | Planowanie oferty/personelu |

## B. Zachowania mieszkańców (kod domowy z `card_home` = modalny `pstl_cd_enr` karty)
| Statystyka | Kolumny | Decyzja |
|---|---|---|
| **Samowystarczalność:** % transakcji codziennych (spożywcze, apteki, paliwo, piekarnie) w obszarze domowym | `mrch_catg_nm`, kod domowy vs kod transakcji | Czy miasto traci funkcje |
| **Odpływ:** dokąd jeżdżą po zakupy (top 5 obszarów) | j.w. | Z kim tworzyć związek |
| Napływ: skąd przyjeżdżają kupujący spoza obszaru | j.w. | Zasięg oddziaływania |
| Odpływ wg kategorii | `mrch_catg_nm` | Jakich usług brakuje lokalnie |
| Mediana odległości zakupów od domu | centroidy kodów | Dostępność usług |
| Udział e-commerce | `channel_flg` (eci, recur), `LARGE DIGITAL GOODS` | Ucieczka poza lokalny handel |

## C. Czas i rytm dnia
| Statystyka | Kolumny | Uwaga |
|---|---|---|
| Heatmapa godzina × dzień tygodnia (wg kategorii) | `tran_id_gmt_tm`, `prch_dt` | Bez godz. 00, GMT → czas PL |
| Weekend vs dzień roboczy | j.w. | Miasto sypialnia czy usługowe |
| Godziny szczytu: turyści vs mieszkańcy | j.w. + `issr_jurn` | Udział gości: ~2% rano, 5–8% po 20:00 |
| Trend miesięczny i YoY (H1 2025 vs H1 2026) | `prch_mnth_id` | Kondycja obszaru |

## D. Wartość i segmentacja
| Statystyka | Kolumny | Uwaga |
|---|---|---|
| Mediana/p95 rachunku, rozkład | `cs_tran_amt` | Ogon do ok. 3 mln |
| Karta premium vs zwykła | `crd_typ_nm` | INFINITE (152) ≈ CLASSIC (148); PLATINUM 259 (jednostki fikcyjne) – hipoteza „premium = zamożny” słaba |
| Karty firmowe osobno | `crd_typ_nm` | Patrz problem 6 |
| Metody płatności: tap, mobile, chip, gotówka | `channel_flg`, `transaction_pos_entry_mode` | Adopcja cyfrowa |

## E. Wskaźniki syntetyczne
1. **Indeks samowystarczalności** = % zakupów codziennych zrobionych lokalnie.
2. **Indeks atrakcyjności** = napływ / (napływ + odpływ), liczony na kartach.
3. **Zależność od turystyki** = udział obrotu od gości (zagraniczni + krajowi spoza obszaru).
4. **Trend funkcji miejskich** = zmiana samowystarczalności m/m – wykrywa miasta „tracące funkcje”.
5. **Siła powiązania dwóch obszarów** = przepływ A→B i B→A znormalizowany do wielkości; ranking par = kandydaci na związek aglomeracyjny (rdzeń Megapolis).
6. **Klasteryzacja obszarów** (K-Means) po profilu kategorii i godzin: turystyczny, sypialnia, handlowy, tranzytowy.
7. **Anomalie** (IsolationForest): nagłe skoki/spadki w obszarze.

## Kolejność MVP
1. Klik na mapie → obszar + liczba turystów + kraje + średni rachunek (A).
2. Panel: heatmapa godzin i trend miesięczny (C).
3. Samowystarczalność i odpływ (B, E1).

Zapytania na sample trwają minuty – wyniki liczyć offline do `dataset/marts/*.parquet`, aplikacja czyta tylko je.

## Wyniki weryfikacji (sample, 2026-09-29)

Skrypty: testy 1–7 (polscy sprzedawcy) i test 8 (karty, wszystkie kraje sprzedawców).

| # | Test | Wynik |
|---|---|---|
| 1 | Brak `pstl_cd_enr`/`fua_enr` wg `issr_jurn` | Domestic 19,6%, Intra 58,7%, **Inter 100%** (głównie okna bez danych, patrz „Weryfikacja ze słownikiem”) |
| 2 | Zgodność `pstl_cd_enr` z `mrch_postal_code` (dokładna / prefiks 2 cyfr) | Domestic 33,7% / 63,2%; **Intra 0,0004% / 0,7%** |
| 3 | Zgodność dokładna wg kanału | tap 39%, mobile 26%, cash 4%, **eci 1,9%, recur 1,2%, moto 1,3%** |
| 4 | Przykłady niezgodności | część to sąsiedni kod w tym samym mieście (Wrocław 50-075 vs 50-077), część zupełnie inny region (sklep w Siedliskach 67-112, kod 33-170 Tarnów) |
| 6 | Godzina 00 | 31,3 mln wierszy to dokładnie `000000` (brak czasu); tylko 1,3 mln ma prawdziwe 00:xx |
| 7 | Różnych kodów: sprzedawcy vs `_enr` | Intra: 17,9 tys. kodów sprzedawców vs **44,1 tys. kodów `_enr`** (więcej niż kodów w Polsce → kody zagraniczne) |
| 8 | Karty z ≥10 transakcjami: ile ma dokładnie jeden `pstl_cd_enr` | **tylko 30%** (Domestic), 41% (Intra), 35% (Inter); mediana **2** różnych `_enr` na kartę vs **21** różnych kodów sprzedawców |

Test 5 (próbka wierszy kart zagranicznych) zwrócił pusty wynik – `USING SAMPLE` jest stosowane przed filtrem; nie powtarzany, bo test H go zastępuje.

### Testy rozstrzygające, czym jest `pstl_cd_enr` (wycinek: 1% kart wg `hash(card)%100=0`, 19,4 tys. kart, 3,07 mln transakcji)

| # | Test | Wynik | Co znaczy |
|---|---|---|---|
| H | Format kodu `_enr` wg kraju wydawcy karty | wydawca DE → `21465`, UK → `BH1 4HN`, CZ → `735 81`, SK → `058 01`, LT → `LT-44192`, PL → `86-100` | Kod jest z kraju **wydawcy**, czyli to kod kupującego |
| F | Ile różnych miast sprzedawców przy jednym `_enr` (ta sama karta, miesiąc) | mediana **4**; 97,6% ma więcej niż jedno | Kod nie zależy od miejsca zakupu |
| C | Modalny `_enr` karty vs modalny kod sprzedawcy w zakupach codziennych (Domestic, PL) | dokładnie **55,6%**, prefiks 3 cyfr **77,5%**, prefiks 2 cyfr **79,6%** | Ludzie robią zakupy codzienne blisko kodu domowego – zgodne z „dom” |
| A | Różnych `_enr` na kartę w miesiącu (≥5 transakcji) | **85,8%** kart-miesięcy ma jeden kod, mediana 1 | W krótkim oknie kod jest stabilny |
| B | Udział najczęstszego `_enr` na kartę (≥10 transakcji z kodem) | mediana 0,50; **≥80%: 47%**, ≥50%: 76% kart | W całym okresie (18 mies.) kod się zmienia; potrzebne okno czasowe |
| B2 | Udział drugiego kodu | u 55% kart drugi kod ma ≥20% transakcji | Jest realny drugi kod |
| E | Drugi kod vs pierwszy w czasie (karty z drugim ≥20%) | zakresy dat **nakładają się u 61%**, sekwencyjne (przeprowadzka) u 39% | To nie tylko przeprowadzki |
| D | Kontekst zakupów pod kodem 1 vs kodem 2 (dzień roboczy 8–17, weekend, kategorie) | praktycznie identyczny (55,3% vs 55,4% dni roboczych; spożywcze 45,5% vs 45,0%) | Drugi kod **nie** jest „pracą” |
| G | Braki `_enr` per karta | Domestic: 5% kart bez kodu, 11% zawsze z kodem, **84% mieszane**; Intra: 41% bez, 25% zawsze, 34% mieszane; Inter: 100% bez | **Uwaga:** wynik zniekształcony oknami bez danych; w oknach z danymi braki to ~1,2% i są całodniowe na karcie |

### Wnioski

1. **`pstl_cd_enr` = kod pocztowy przypisany do karty (szacowane miejsce stałego przebywania, potwierdzone słownikiem)** (a `lau_enr`/`fua_enr` = jego gmina/obszar funkcjonalny). Dowody: kod w formacie kraju wydawcy; niezależny od miasta sprzedawcy (F); zgodny z tym, że zakupy codzienne robi się blisko domu (C).
2. **Nie jest stały:** ~14% kart-miesięcy ma więcej niż jeden kod (A), a w 18 miesiącach zaledwie 47% kart ma dominujący kod ≥80% (B). Drugi kod nie odpowiada „pracy” (D), więc jest to raczej szum wzbogacenia lub zmiana danych adresowych. Przyczyny nie ustaliliśmy.
3. **Turyści zagraniczni:** lokalizacja zakupu po `mrch_postal_code`; pochodzenie po `pstl_cd_enr` (Intra: ok. 74% transakcji w okresach z danymi; Inter tylko kraj wydawcy).
4. **`card_home` = modalny `pstl_cd_enr`** z wierszy z kodem, liczony w oknie czasowym (do sprawdzenia: kwartał vs cały okres), z polem pewności (udział modalnego). Własna heurystyka z zakupów codziennych zostaje jako walidacja (zgodność 56% dokładnie, 78% do prefiksu 3 cyfr).
5. Nowe możliwości wynikające z tego: region pochodzenia turysty do kodu pocztowego oraz odpływ transgraniczny Polaków (karty PL u sprzedawców za granicą).
6. Godzina: filtrować `tran_id_gmt_tm <> '000000'`, nie całą godzinę 00.

### Ograniczenia i co jeszcze niesprawdzone
- Słownik nie opisuje okna czasowego ani częstotliwości przeliczania przypisania `*_enr` ani powodu pustych okien – to pytanie do organizatorów DataSprint.
- Test na 1% kart z sample; nie sprawdzano, czy wynik jest taki sam na full.
- Do sprawdzenia: czy zmienność kodu zależy od miesiąca/okresu wzbogacenia (np. skoki na granicach kwartałów), oraz jakie okno (miesiąc, kwartał) daje najlepszy kompromis stabilność–pokrycie.
- Znaczenie `issr_jurn` potwierdzone słownikiem (Domestic/Intra/Inter jak wyżej).

## Weryfikacja ze słownikiem (`docs/Dictionary_data_Visa.xlsx`)

| Temat | Słownik | Zgodność z analizą |
|---|---|---|
| `pstl_cd_enr`, `lau_enr`, `fua_enr` | „Kod pocztowy / obszar przypisany do karty”; `lau_enr` = „~miejsce stałego przebywania posiadacza karty na podstawie wykonywanych transakcji” | **Potwierdza** hipotezę (kupujący, nie sprzedawca), ale doprecyzowuje: to **szacunek z transakcji**, nie adres. Tłumaczy zmienność w czasie |
| `issr_jurn` | Domestic = ten sam kraj; Intra = inny kraj, ten sam region Visa; Inter = inny region Visa | **Potwierdza** wcześniejsze wnioskowanie |
| `tran_id_gmt_tm` | GMT/UTC, HHMMSS | Zgodne; `000000` nie jest opisane jako brak czasu – nadal traktować jako podejrzane |
| `cs_tran_amt` | **Waluta fikcyjna** (hackathon) | **Korekta:** usunięto „zł” z dokumentu; tylko porównania względne |
| `prod_id_pltfrm_cd_vcis` | Segment karty: CN konsument, CO commercial, BZ business, GV government | **Nowe:** do wyłączania kart firmowych (lepsze niż `crd_typ_nm`); nie analizowane liczbowo |
| `cp_flag` | 1 = karta obecna, 0 = bez fizycznej obecności (online) | **Nowe:** e-commerce mierzyć `cp_flag=0` (11% transakcji), a nie samym `eci` |
| `channel_flg` `mobile` | Płatność zainicjowana z aplikacji/portfela w aplikacji, **nie** zbliżeniowa w terminalu | Uściśla opis: `mobile` ≠ tap; `cp_contactless` = tap/NFC |
| `mrch_city_nm_raw` | „Miasto, w którym miała miejsce transakcja” | Zgodne |
| `report_ctry` | Kod kraju raportowania | Niewykorzystane |

### Nowe ustalenia z testów po lekturze słownika (wycinek 1% kart, sprzedawca w PL, Domestic)

1. **Okna bez danych `_enr`:** null-share `pstl_cd_enr` wynosi ~1–2% do 2026-02-27, potem: 2026-02-28…03-30 ≈ 100%, 2026-03-31…04-29 ≈ 2–3%, od 2026-04-30 ≈ 100% (do końca czerwca). Dla Intra podobnie (~26% braków w oknach z danymi, ~100% w oknach bez). `mrch_postal_code` nie ma tego problemu (braki 3–8%).
2. **Przypisanie jest dzienne:** w obrębie karty i dnia wartość jest stała u 99,9% kart-dni, w tygodniu u 96,6%, w miesiącu u 89,7%. Braki są „całodniowe” (mieszane null/nie-null w obrębie dnia: 0,08%).
3. **Przypisanie zmienia się w czasie:** modalny kod karty zmienia się między kolejnymi miesiącami w 39% przypadków, a w 18% zmienia się nawet region (pierwsze 2 cyfry). To zgodne ze słownikiem („~stałe miejsce przebywania na podstawie transakcji” – najpewniej okno kroczące), więc `card_home` jest **przybliżeniem**, a nie stałym adresem.
4. **Konsekwencja dla architektury:**
   - `card_home` liczyć z okresu z danymi i przypisać do wszystkich transakcji karty (patrz problem 5).
   - Trend „tracące funkcje” z użyciem `_enr` możliwy tylko w oknach z danymi (14 mies. + kwiecień 2026); trendy oparte o `mrch_postal_code` (turyści, kategorie, godziny) działają na całym okresie.
   - Porównanie H1 2025 vs H1 2026 dla wskaźników z kodem domowym niemożliwe wprost (brak marca i maja–czerwca 2026) – użyć wspólnych miesięcy (styczeń–luty).
