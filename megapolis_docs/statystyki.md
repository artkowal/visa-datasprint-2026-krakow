# Statystyki do analizy – lista i uwagi o jakości danych

Podstawa: profilowanie `dataset/datasprint_sample_data.parquet` (305 mln wierszy; polscy sprzedawcy: 260 mln).
Każda statystyka ma przypisaną decyzję, którą wspiera.

## Problemy z danymi do rozwiązania przed MVP

1. **Turyści a geolokalizacja `_enr`.** W FUA Kraków/Warszawa/Tarnów udział kart zagranicznych ≈ 0%, choć globalnie to ok. 3%.
   **Potwierdzone:** `pstl_cd_enr`/`fua_enr` brak dla 100% kart Inter i 59% Intra. Do turystów użyć `mrch_postal_code` / `mrch_city_nm_raw`.
2. **`pstl_cd_enr` vs `mrch_postal_code`** zgadzają się tylko w ok. 33% wierszy – to dwie różne geografie. Wstępnie `_enr` wygląda na geografię kupującego, ale nie jest stałym atrybutem karty (patrz „Wyniki weryfikacji”). Do „gdzie zaszła transakcja” używać `mrch_postal_code`.
3. **Godzina 00 to artefakt** (32 mln wierszy, 12%, średnia kwota 225; godziny 01–03 mają po kilkaset tys.). Analiza godzinowa bez godz. 00, z raportem ile odrzucono. Czas jest w GMT – przesunąć na czas polski.
4. **Kod domowy karty (heurystyka)** – pewny (≥10 transakcji codziennych i ≥50% w jednym kodzie) tylko dla ok. 60% kart krajowych. Wskaźniki „mieszkańcy” liczyć na tej podgrupie i pokazywać pokrycie.
5. **~21% transakcji u polskich sprzedawców bez `pstl_cd_enr`/`lau_enr`/`fua_enr`** (głównie e-commerce/brak dopasowania) – pokazywać jako „brak lokalizacji”.
6. **Karty BUSINESS** (śr. 517 zł vs 148 zł CLASSIC) zaburzają średnie – wyłączać lub pokazywać osobno. Kwoty: używać mediany i p95 (mediana 52 zł, średnia 161 zł).

## A. Turyści i goście (po kliknięciu obszaru)
| Statystyka | Kolumny | Decyzja |
|---|---|---|
| Liczba transakcji i kwota od kart zagranicznych, udział w obrocie | `issr_jurn`, `issr_ctry_nm`, `cs_tran_amt` | Jak bardzo obszar żyje z turystyki |
| Kraje pochodzenia (top 10) | `issr_ctry_nm` | Do kogo kierować ofertę |
| Średni rachunek wg kraju | j.w. | Kogo opłaca się przyciągać (UA: 121 zł, DE: 354, CZ: 320) |
| Turysta krajowy (karta PL, kod domowy poza obszarem) | `card_home` | Ruch z innych regionów |
| Udział kart premium wśród gości | `crd_typ_nm` | Segment zamożny |
| Sezonowość gości | `prch_mnth_id`, `myweek` | Planowanie oferty/personelu |

## B. Zachowania mieszkańców (kod domowy z `card_home`)
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
| Karta premium vs zwykła | `crd_typ_nm` | INFINITE (152 zł) ≈ CLASSIC (148 zł); PLATINUM 259 zł – hipoteza „premium = zamożny” słaba |
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
| 1 | Brak `pstl_cd_enr`/`fua_enr` wg `issr_jurn` | Domestic 19,6%, Intra 58,7%, **Inter 100%** |
| 2 | Zgodność `pstl_cd_enr` z `mrch_postal_code` (dokładna / prefiks 2 cyfr) | Domestic 33,7% / 63,2%; **Intra 0,0004% / 0,7%** |
| 3 | Zgodność dokładna wg kanału | tap 39%, mobile 26%, cash 4%, **eci 1,9%, recur 1,2%, moto 1,3%** |
| 4 | Przykłady niezgodności | część to sąsiedni kod w tym samym mieście (Wrocław 50-075 vs 50-077), część zupełnie inny region (sklep w Siedliskach 67-112, kod 33-170 Tarnów) |
| 6 | Godzina 00 | 31,3 mln wierszy to dokładnie `000000` (brak czasu); tylko 1,3 mln ma prawdziwe 00:xx |
| 7 | Różnych kodów: sprzedawcy vs `_enr` | Intra: 17,9 tys. kodów sprzedawców vs **44,1 tys. kodów `_enr`** (więcej niż kodów w Polsce → kody zagraniczne) |
| 8 | Karty z ≥10 transakcjami: ile ma dokładnie jeden `pstl_cd_enr` | **tylko 30%** (Domestic), 41% (Intra), 35% (Inter); mediana **2** różnych `_enr` na kartę vs **21** różnych kodów sprzedawców |

Test 5 (próbka wierszy kart zagranicznych) zwrócił pusty wynik – `USING SAMPLE` jest stosowane przed filtrem; do powtórzenia z `LIMIT`.

### Wnioski

1. **Potwierdzone:** kart zagranicznych nie da się zlokalizować po `pstl_cd_enr`/`fua_enr` (Inter 100% braków, Intra 59%). Turystów lokalizować po `mrch_postal_code` / `mrch_city_nm_raw` (braki tylko ok. 4,5%).
2. **Potwierdzone:** `pstl_cd_enr` to inna geografia niż `mrch_postal_code`. Nie wolno ich mieszać w jednym wskaźniku.
3. **Nie jest to geografia sprzedawcy.** Karta ma średnio 21 różnych kodów sprzedawców, a tylko mediana 2 różnych `pstl_cd_enr`; u kart Intra kody `_enr` są zagraniczne i nie pasują do żadnego polskiego sprzedawcy; przy e-commerce zgodność spada do ~2%.
4. **Hipoteza robocza (NIE potwierdzona):** `pstl_cd_enr` opisuje kupującego (kod domowy/pracy), ale **nie jest stałym atrybutem karty** – tylko 30% kart ma jeden kod. Możliwe wyjaśnienia: dwa punkty zakotwiczenia (dom + praca), zmiana w czasie (przeprowadzka, aktualizacja danych), albo wzbogacenie liczone per transakcja/okres.
5. **Konsekwencja dla planu:** heurystyki kodu domowego z `card_home` **nie porzucamy**. Do czasu rozstrzygnięcia liczymy kod domowy z własnej heurystyki (modalny kod z transakcji codziennych) i **porównujemy go** z modalnym `pstl_cd_enr` karty. Zgodność obu jest miarą wiarygodności.
6. Godzina: filtrować `tran_id_gmt_tm <> '000000'`, nie całą godzinę 00.

### Następne testy (krótkie, na podzbiorze kart)
- Rozkład `pstl_cd_enr` w czasie dla jednej karty: czy zmienia się między miesiącami (`prch_mnth_id`), czy jest stały w miesiącu.
- Udział najczęstszego `pstl_cd_enr` na kartę (jeśli ≥80% – traktujemy jako kod domowy).
- Zgodność modalnego `pstl_cd_enr` karty z modalnym kodem sprzedawcy w kategoriach codziennych.
- Czy `pstl_cd_enr` zależy od kategorii/kanału w obrębie jednej karty (dom vs praca).
