# Megapolis VISA – dokumentacja techniczna


## 1. Cel i zakres

Aplikacja pokazuje na mapie Polski gminy i pozwala:

1. **wybrać jedną lub kilka gmin** i zobaczyć ich profil zakupowy: kto kupuje (mieszkańcy, goście z Polski, goście z zagranicy), jak płaci, co kupuje, kiedy i skąd są goście;

2. **zobaczyć powiązania mieszkańców** z innymi gminami (samowystarczalność, odpływ, napływ, atrakcyjność);

3. **znaleźć gminy do współpracy** w dwóch trybach: *Wzmocnienie* (podobne mocne kategorie) i *Uzupełnienie* (kategorie wzajemnie wypełniające luki).

Dane wejściowe to transakcje Visa (próbka 20% kart z pełną historią) oraz GeoJSON kodów pocztowych z przypisaniem do gmin. **Kwoty są w walucie fikcyjnej** – wolno używać tylko porównań względnych.


## 2. Struktura projektu

```
streamlit_app.py            ekran główny: mapa + porównanie wybranych gmin
build_marts.py              budowa tabel g_*.parquet i tematów t_*.json (DuckDB, jedno przejście)
pages/2_Dopasowania.py      osobna strona dopasowań gmin
app/
  __init__.py
  map_builder.py            scalanie kodów w gminy, geometria, mapa Plotly
  marts.py                  tematy JSON: summary, by_country, by_month, by_hour, by_card, by_channel, residents
  queries.py                odczyt tematów t_*.json + starsze zapytania DuckDB po surowym parquet
  panels.py                 panele Streamlit dla jednej gminy (sekcje: kupujący, płatności, produkty, czas, goście)
  trade.py                  ocena handlu: specjalizacje, luki, różnorodność, benchmark podobnych gmin
  categories.py             grupowanie kategorii sprzedawców (MCC nazwy) w 16 grup
  analytics.py              analizy A–E dla listy kodów pocztowych (polars)
  matching_view.py          widok dopasowań (UI)
  matching_map.py           mapa dopasowań
  matching_real.py          ranking dopasowań na profilach z danych
  matching_demo.py          ranking demonstracyjny (dane syntetyczne)
  charts.py                 wykresy matplotlib → base64 (starsze, zastępowane Plotly/Altair)
assets/megapolis-visa.svg   logo
geojson/postcodes_poland.geojson   kolumny: Name (kod pocztowy), Gmina (nazwa gminy)
dataset/
  datasprint_sample_data.parquet   surowe transakcje
  marts/                    g_*.parquet, postal_gmina.parquet, _meta.json
  json/                     t_*.json, _meta.json, tematy z app/marts.py, by_category.json
```

### Zależności

`streamlit` (używane: `st.fragment`, `st.rerun(scope=…)`, `width="stretch"`), `plotly` ≥ 5.24 (trace'y `Choroplethmap`, `Scattermap`), `altair`, `pandas`, `numpy`, `polars`, `duckdb`, `geopandas`, `shapely`, `matplotlib` (tylko `charts.py`), opcjonalnie `orjson`.


## 3. Dane wejściowe

### 3.1 Surowy parquet (`dataset/datasprint_sample_data.parquet`)

Kolumny używane przez skrypty:

| Kolumna | Użycie |
| - | - |
| `pymt_crd_acct_num_raw` | identyfikator karty (liczenie kart, `card_home`) |
| `mrch_ctry_cd` / `mrch_ctry_nm` | kraj sprzedawcy (616 = Polska; `build_marts.py` filtruje po nazwie `POLAND`) |
| `mrch_postal_code`, `mrch_city_nm_raw` | lokalizacja sprzedawcy (kod pocztowy → gmina) |
| `mrch_catg_cd`, `mrch_catg_nm` | kategoria sprzedawcy (MCC i nazwa) |
| `issr_jurn`, `issr_ctry_nm` | pochodzenie karty (`Domestic` / zagraniczna; kraj wydania) |
| `pstl_cd_enr`, `lau_enr` | szacowane miejsce stałego przebywania karty (kod pocztowy, gmina) |
| `prod_id_pltfrm_cd_vcis` | segment karty (`CN` = konsumencka; `CO`, `BZ`, `GV` = firmowe/rządowe) |
| `crd_typ_nm` | typ karty (premium: INFINITE, PLATINUM, PREMIER, VISA SIGNATURE CARD) |
| `channel_flg`, `cp_flag`, `transaction_type` | kanał płatności, karta obecna (1) / nieobecna (0), ATM |
| `tran_id_gmt_tm`, `prch_dt`, `prch_mnth_id` | czas (GMT), data (może być serialem Excela), miesiąc |
| `cs_tran_amt` | kwota (waluta fikcyjna) |


**Okna bez danych `_enr`:** kolumny `pstl_cd_enr`/`lau_enr` są puste od 2026-02-28 do 2026-03-30 i od 2026-04-30 do 2026-06-30. Kod używa tych dat w `marts.py` i `analytics.py`.

### 3.2 GeoJSON (`geojson/postcodes_poland.geojson`)

Wielokąty kodów pocztowych z właściwościami `Name` (kod `NN-NNN`) i `Gmina` (nazwa gminy; klucze w aplikacji to nazwy wielkimi literami, np. `KRAKOW`). Nie ma TERYT ani powiatu, więc **nazwa gminy jest kluczem** (homonimy się zlewają).


## 4. Potok danych

```
flowchart LR
  P[(parquet transakcji)] --> B[build_marts.py]
  G[(GeoJSON kodów)] --> B
  B --> M[dataset/marts/g_*.parquet<br/>postal_gmina.parquet]
  B --> T[dataset/json/t_*.json<br/>_meta.json]
  P --> A[app/marts.py<br/>ensure_topic]
  G --> A
  A --> S[dataset/json/summary, by_*, residents]
  T --> Q[app/queries.py]
  Q --> PN[app/panels.py + trade.py]
  S --> APP[streamlit_app.py]
  BC[by_category.json] --> MR[matching_real.py]
  T --> APP
```

Są **dwa równoległe źródła JSON** (patrz sekcja 9): `build_marts.py` → tematy `t_*` (czytane przez `queries.py`/`panels.py`) oraz `app/marts.py` → tematy `summary`, `by_*`, `residents` (czytane przez `streamlit_app.py`).

### 4.1 `build_marts.py`

Buduje małe tabele na poziomie gminy jednym przejściem DuckDB (`GROUPING SETS`).

```
python build_marts.py                                        # sample
python build_marts.py --source dataset/datasprint_full_data.parquet
python build_marts.py --export-only                          # tylko JSON z istniejących g_*.parquet
# opcje: --out dataset/marts  --json-dir dataset/json  --memory 5GB  --threads 3
```

**Filtry:** sprzedawca w Polsce (`mrch_ctry_nm = 'POLAND'`), karty konsumenckie (`CN`), bez `ATM` i bez `channel_flg = 'cash'`.

**Mapowanie kod → gmina (`postal_gmina.parquet`, kolumny `postal`, `gmina`, `n_gmin`):** dla każdego kodu wybierana jest gmina o największej powierzchni wielokątów kodu (pole liczone w EPSG:2180). `n_gmin` mówi, do ilu gmin należy kod. Kod sprzedawcy normalizowany jest do 5 cyfr → `NN-NNN`.

**Typ kupującego (`visitor`)** liczony dla każdej transakcji:

| Wartość | Warunek |
| - | - |
| `zagr` | karta wydana poza Polską |
| `mieszk` | karta polska, `upper(lau_enr)` = gmina sprzedawcy |
| `pl_gosc` | karta polska, `lau_enr` = inna gmina |
| `nieznany` | karta polska bez `lau_enr` (okna bez `_enr`) |


**Czas polski:** godzina = (godzina GMT + 1 lub 2) mod 24, przy czym +2 obowiązuje między 2025-03-30 a 2025-10-25 oraz od 2026-03-29 (przybliżenie czasu letniego; w dniach przejścia możliwe drobne odchylenia). Dzień tygodnia (`dow`, 0 = niedziela) uwzględnia przejście przez północ. Zapis `000000` oznacza brak czasu i daje `hr = -1`, `dow = -1`.





**Tabele pośrednie** (`dataset/marts/`):

| Tabela | Ziarno | Miary |
| - | - | - |
| `g_cat` | gmina × visitor × kategoria | `n_tx`, `amt` |
| `g_pay` | gmina × visitor × kanał × `cp_flag` | `n_tx`, `amt` |
| `g_month` | gmina × visitor × miesiąc | `n_tx`, `amt` |
| `g_hour` | gmina × visitor × dzień tygodnia × godzina | `n_tx`, `amt` |
| `g_country` | gmina × kraj wydania karty (bez POLAND) | `n_tx`, `amt` |
| `g_card` | gmina × visitor × premium | `n_tx`, `amt` |


**Tematy JSON** (`dataset/json/`, format `{"cols": [...], "data": {gmina: [[...], ...]}}`, klucz `_PL` = suma krajowa tam, gdzie ma sens):

| Plik | Kolumny wiersza | Uwagi |
| - | - | - |
| `t_structure.json` | `grupa, visitor, n, amt` | grupa kategorii × kupujący |
| `t_categories.json` | `cat, grupa, n, avg_amt, mieszk, pl_gosc, zagr, nieznany` | top 15 kategorii na gminę |
| `t_visitors.json` | `visitor, n, amt` | + `_PL` |
| `t_payments.json` | `visitor, ch, cp, n` | + `_PL` |
| `t_months.json` | `visitor, mon, n` |  |
| `t_hours.json` | `visitor, dow, hr, n` | `hr = -1` = brak czasu |
| `t_countries.json` | `country, n, avg_amt` | top 10; `extra.foreign_total` = suma zagraniczna |
| `t_cards.json` | `visitor, prem, n` | + `_PL` |
| `t_dominant.json` | `grupa, n, pct, avg_amt` | jeden wiersz: dominująca grupa gminy |
| `_meta.json` | – | źródło, `source_kind` (sample/full), data budowy, pokrycie, miesiące bez pochodzenia |


**`_meta.json`** zawiera m.in. `pct_with_postal` (udział transakcji z poprawnym kodem), `pct_mapped_to_gmina`, `unknown_origin_share_by_month` i `origin_missing_months` (miesiące, w których ponad 50% transakcji polskimi kartami nie ma `lau_enr`).

### 4.2 `app/marts.py`

Ładuje tematy z `dataset/json/<temat>.json`; jeśli pliku brak, **generuje go przy pierwszym użyciu** (skan surowego parquet – może trwać długo).

```
from app.marts import ensure_topic, ensure_all, get_gmina
ensure_all()                       # wygeneruj wszystkie brakujące
get_gmina("KRAKOW", "summary", "residents")
```

Filtr bazowy: sprzedawca w Polsce (`mrch_ctry_cd = 616`), niepusty kod pocztowy, czas różny od `000000`. Mapowanie kod → gmina bierze z GeoJSON (`Name` → `Gmina`).

| Temat | Struktura `{gmina: …}` |
| - | :-: |
| `summary` | `{n_total, n_cards, n_foreign, n_domestic, pct_foreign, amt_median, amt_sum}` |
| `by_country` | lista `{country, n, pct}` (top 10 zagranicznych) |
| `by_month` | lista `{month, n, n_foreign, pct_foreign}` |
| `by_hour` | lista `{hour, n, n_foreign, pct_foreign}` (godzina = GMT + 1, mod 24) |
| `by_card` | lista `{type, n, pct}` |
| `by_channel` | lista `{channel, n, pct}` |
| `residents` | `{n_resident_cards, B1…B4, E1…E5}` (poniżej) |


**Mieszkańcy (`residents`)** – dwa skany DuckDB:

1. `card_home`: dla każdej karty modalny `pstl_cd_enr` (poza oknami bez danych), zaakceptowany gdy jego udział ≥ 50% i kod mapuje się na gminę.

2. `cp_flows`: transakcje kart krajowych, karta obecna (`cp_flag = 1`), bez segmentów `CO/BZ/GV`, u polskich sprzedawców, zagregowane jako gmina domowa × gmina zakupu × kategoria.

Wskaźniki:

| Klucz | Definicja |
| - | - |
| `B1_self_sufficiency` (= `E1`) | % zakupów codziennych (MCC 5411, 5499, 5912, 5541, 5542, 5462, 5451, 5422) mieszkańców zrobionych w gminie domowej |
| `B2_outflow` | top 8 gmin, do których jeżdżą mieszkańcy (`area_gmina`, `n`) |
| `B3_inflow` | top 8 gmin, z których przyjeżdżają do tej gminy (`home_gmina`, `n`) |
| `B4_outflow_cat` | top 10 kategorii kupowanych poza gminą |
| `E2_attractiveness` | napływ / (napływ + odpływ) × 100 |
| `E3_tourism_dependency` | % transakcji w gminie od kart z domem poza gminą |
| `E5_connections` | top 8 powiązań: `{gmina, kierunek (→ ← ↔), n_out, n_in, flow_total}` |


### 4.3 `by_category.json` (profile kategorii)

Czytany przez `matching_real.py`, `matching_view.py` i ekran główny. Format:

```
{ "KRAKOW": {"Żywność": 0.21, "Gastronomia": 0.12, "...": 0.0}, "...": {} }
```

Klucze to gminy, wartości to **udziały** grup kategorii (nazwy z `categories.GROUP_ORDER`, bez „Handel internetowy” i „Inne”; suma ≈ 1). **Żaden z przesłanych skryptów nie generuje tego pliku** – trzeba go wytworzyć osobno (naturalne źródło: `t_structure.json`, udział lokalnych grup w transakcjach gminy). Gdy pliku brakuje, `matching_real` używa `t_dominant.json` (profil 0/1 dla dominującej grupy), a `matching_view` pokazuje ostrzeżenie o danych demonstracyjnych.


## 5. Aplikacja Streamlit

### 5.1 `streamlit_app.py` (ekran główny)

Uruchomienie: `streamlit run streamlit_app.py`. Wymaga `assets/megapolis-visa.svg`.

Przebieg:

1. **Start (cache):** `load_gminy_data` (scalona geometria gmin, mapowanie gmina → kody, centroidy), `get_dominant_categories`, `load_display_profiles`.

2. **Mapa** w `@st.fragment`: przełącznik widoku *Statystyki gmin* / *Dominujące kategorie*, wyszukiwarka gminy (animowany „fly-to” przez JS), kliknięcie gminy dodaje/usuwa ją z zaznaczenia (`st.session_state["selected"]`). Figury są cache'owane w słowniku (do 40 pozycji, klucz: zbiór zaznaczonych + widok).

3. **Bez zaznaczenia** aplikacja pokazuje podpowiedź i zatrzymuje się (`st.stop()`).

4. **Po zaznaczeniu:** ładuje tematy (`summary, by_country, by_month, by_hour, by_card, by_channel, residents, t_dominant`) i pokazuje:

   - nagłówki gmin z dominującą kategorią (pierwsza wybrana gmina = **referencja** dla delt),

   - wykres profilu kategorii (tryb wartości lub różnic w pp od referencji),

   - dla każdej gminy: **Turyści** (metryki z deltą, top kraje, goście per miesiąc, typ karty), **Rytm dnia** (trend miesięczny, % zagranicznych per godzina), **Płatności** (kanały), **Mieszkańcy i powiązania** (E1–E3, E5, B2–B4).

### 5.2 `../pages/2_Dopasowania Gmin.py`

Osobna strona: wybór trybu (*Wzmocnienie* / *Uzupełnienie*) i wywołanie `render_matching(mode)`.


### 5.3 `app/map_builder.py`

| Funkcja | Opis |
| - | - |
| `load_gminy_data(geojson_path)` | Zwraca `(geojson gmin, {gmina: [kody]}, {gmina: (lat, lon)})`. Scala kody w gminy (`dissolve`), zamyka szczeliny buforem ±30 m, wypełnia dziury \< 0,5 km², upraszcza geometrię (tolerancja 0,0025°). |
| `build_map(...)` | Figura Plotly: warstwa gmin niezaznaczonych (kolor wg dominującej grupy kategorii lub paleta domyślna), warstwa zaznaczonych (fiolet, biały obrys), opcjonalnie linie od centrum do sąsiadów. `uirevision` zachowuje pan/zoom między odświeżeniami. |


Kolory grup kategorii definiuje `_GROUP_COLORS`.

### 5.4 `app/panels.py` (panele gminy)

Punkt wejścia: `render_gmina(g, trade_ref, meta)`. Kolejność sekcji:

1. **Nagłówek** – transakcje w próbce, szacunek dla wszystkich kart (× `SAMPLE_SCALE` = 4,96, tylko gdy `source_kind == "sample"`), średni rachunek względem Polski.

2. **Kto tu kupuje?** – udziały mieszkańców, gości z Polski, gości z zagranicy i „bez danych o pochodzeniu” na tle Polski.

3. **Jak płacą?** – na miejscu (`cp_flag = 1`) vs online/zdalnie, metody płatności, udział online wg typu kupującego.

4. **Co kupują i kto?** – dominująca grupa, różnorodność oferty, mocne strony i luki względem podobnych gmin.

5. **Kiedy kupują?** – miesiące i heatmapa godzina × dzień tygodnia (czas PL).

6. **Skąd są goście?** – kraje wydania kart, udział kart premium.

7. **Szczegóły** – tabele kategorii, grup vs podobne gminy, płatności oraz zakładka „Jakość danych” z metadanymi budowy.

Bramki jakości: brak danych → informacja; poniżej `MIN_TX` (1000) transakcji → ostrzeżenie i brak wskaźników.

### 5.5 `app/queries.py`

**Tematy JSON (zalecane):**

| Funkcja | Zwraca |
| - | - |
| `marts_ready()` | czy istnieją wszystkie pliki `t_*.json` |
| `get_marts_meta()` | zawartość `dataset/json/_meta.json` |
| `get_gmina_group_table()` | tabela gmina × grupa (`n_tx`, `amt`, `guest_tx`) – wejście do `trade.build_reference` |
| `get_structure(g)`, `get_categories(g, limit)` | struktura handlu, top kategorie |
| `get_visitors(g)`, `get_payments(g)`, `get_card_types(g)` | `g=None` → suma krajowa (`_PL`) |
| `get_months(g)`, `get_hours(g)` | trendy i rytm dnia (`dow` 0 = niedziela, `hr = -1` = brak czasu) |
| `get_countries(g, limit)`, `get_countries_total(g)` | kraje gości i suma zagraniczna |
| `get_dominant_categories()` | `{gmina: {grupa, n, pct, avg_amt}}` |


**Starsze zapytania po surowym parquet** (`get_miasta`, `get_top_kategorie`, `get_turysci_kraje`, `get_trendy_miesiac`, `get_kanaly`, `get_stats_postal`, `get_stats_gmina`): działają po nazwie miasta lub kodach `pstl_cd_enr`, budują SQL przez f-stringi i skanują cały plik przy każdym wywołaniu. Zostały zastąpione przez tematy JSON.

### 5.6 `app/trade.py` (ocena handlu)

Wejście: `get_gmina_group_table()`. Wskaźniki liczone są na **transakcjach lokalnych** (bez grup „Handel internetowy” i „Inne”, bo sprzedawcy internetowi są przypisani do siedziby firmy).

| Funkcja | Opis |
| - | - |
| `build_reference(tbl)` | Zestawienie wszystkich gmin: udziały grup, kwoty, transakcje gości, udziały krajowe, różnorodność. Liczone raz. |
| `peers_for(ref, gmina, n=50)` | 50 gmin najbliższych wielkością (log liczby transakcji lokalnych) spośród gmin ≥ `MIN_TX`. |
| `profile(ref, gmina)` | Zwraca `status` (`brak` / `za_malo_danych` / `ok`) oraz tabelę grup z oceną `specjalizacja` / `luka`. |


**Parametry:**

| Stała | Wartość | Znaczenie |
| - | - | - |
| `MIN_TX` | 1000 | poniżej: „za mało danych” |
| `LOW_CONFIDENCE_TX` | 5000 | poniżej: ostrzeżenie o małej próbie |
| `N_PEERS` | 50 | rozmiar grupy porównawczej |
| `SPEC_LQ` | 1,5 | specjalizacja: udział ≥ 1,5× mediany rówieśników |
| `GAP_LQ` | 0,5 | luka: udział ≤ 0,5× mediany rówieśników |
| `MIN_SHARE` | 0,02 | grupa ma znaczenie, gdy rówieśnicy mają ≥ 2% transakcji |
| `MIN_GROUP_TX` | 50 | minimalna liczba transakcji grupy dla oceny |


**Definicje:** LQ = udział grupy w gminie / mediana udziału u rówieśników. *Luka*: mediana rówieśników ≥ `MIN_SHARE`, LQ ≤ `GAP_LQ` i oczekiwana liczba transakcji (mediana × transakcje lokalne) ≥ `MIN_GROUP_TX`. *Specjalizacja*: LQ ≥ `SPEC_LQ`, udział ≥ `MIN_SHARE` i transakcji grupy ≥ `MIN_GROUP_TX`. *Różnorodność* = znormalizowana entropia Shannona udziałów (0 = jedna grupa, 1 = rozkład równy); `diversity_pct_peers` to odsetek rówieśników o niższej różnorodności. `online_share` = 1 − transakcje lokalne / wszystkie.

### 5.7 `app/categories.py`

Mapuje nazwy `mrch_catg_nm` na 15 grup (+ `Inne`): Żywność, Dyskonty i domy towarowe, Gastronomia, Zdrowie i apteki, Uroda, Moda i akcesoria, Dom/ogród/budowa, Elektronika i media, Motoryzacja i paliwa, Transport i parkowanie, Turystyka i nocleg, Rozrywka i sport, Usługi i administracja, Handel internetowy, Pozostały detal. Kategorie spoza słownika trafiają do `Inne`.

Eksport: `CATEGORY_TO_GROUP`, `GROUP_ORDER`, `GROUP_ICONS`, `EXCLUDED_FROM_LOCAL = {"Handel internetowy", "Inne"}`, `group_of()`, `labeled()`.

### 5.8 Dopasowania gmin

| Moduł | Rola |
| - | - |
| `matching_view.py` | UI: wybór gminy bazowej i zasięgu (30–300 km), profil kategorii, karty dopasowań z parami kluczowych kategorii, kliknięcie mapy zmienia gminę bazową |
| `matching_map.py` | mapa: gmina bazowa (fiolet), dopasowania (teal = Wzmocnienie, złoty = Uzupełnienie), pozostałe gminy (szare) |
| `matching_real.py` | ranking na profilach z `by_category.json` (fallback: `t_dominant.json`, potem demo) |
| `matching_demo.py` | ranking demonstracyjny: profile z hasha SHA-256 nazwy gminy (syntetyczne), realna jest tylko odległość |


**Wynik dopasowania (`matching_real.rank_matches`):**

- odległość = haversine między centroidami; kandydaci poza zasięgiem lub bez profilu są pomijani,

- **Wzmocnienie:** `profile_score = Σ_k min(a_k, b_k)` po kategoriach,

- **Uzupełnienie:** `complement_k = (1 − a_k)·b_k + (1 − b_k)·a_k`, `profile_score` = średnia z trzech największych,

- `proximity = 1 − odległość / zasięg`,

- `score = round(100 · (0,8 · min(profile_score, 1) + 0,2 · proximity))`,

- sortowanie: wynik malejąco, odległość, nazwa; domyślnie 5 wyników.

Kategorie profilu: `GROUP_ORDER` bez „Handel internetowy” i „Inne”. W widoku kategoria jest „mocna” od 8% udziału i „słaba” poniżej 4%.

### 5.9 `app/analytics.py` i `app/charts.py`

`analytics.py` to wersja analiz A–E na `polars` dla listy kodów pocztowych: `run_analysis(postal_codes, parquet, with_residents)` (sekcje A turyści, C czas, D wartość, opcjonalnie B) i `run_residents_analysis(postal_codes, code_to_gmina)` (sekcje B i E z pełnego skanu). W `streamlit_app.py` funkcja `run_residents_analysis` jest importowana, ale nie wywoływana.

`charts.py` renderuje wykresy matplotlib jako obrazy base64 (kategorie, kraje, trend, kanały) – starsza warstwa, nieużywana przez opisane widoki.


## 6. Wskaźniki – zestawienie definicji

| Wskaźnik | Definicja | Źródło |
| - | - | - |
| Samowystarczalność | % zakupów codziennych mieszkańców zrobionych w gminie domowej | `marts.py` (`B1`/`E1`) |
| Atrakcyjność | napływ / (napływ + odpływ) | `marts.py` (`E2`) |
| Zależność od gości | % transakcji w gminie od kart z domem poza gminą | `marts.py` (`E3`) |
| % zagranicznych | transakcje kartami z `issr_jurn ≠ Domestic` / wszystkie | `marts.py` (`summary`) |
| Mieszkaniec / gość PL / gość zagr. | patrz tabela w 4.1 | `build_marts.py` |
| Specjalizacja / luka | LQ względem 50 podobnych gmin | `trade.py` |
| Różnorodność | znormalizowana entropia grup kategorii | `trade.py` |
| Wynik dopasowania | 0,8 · profil + 0,2 · bliskość, skala 0–100 | `matching_real.py` |



## 7. Zasady interpretacji i ograniczenia

- **Próbka:** losowe 20% kart z pełną historią. Udziały są wiarygodne, wartości bezwzględne skaluje się mnożnikiem ≈ 4,96 (`SAMPLE_SCALE`). Małe gminy mają duży szum.

- **Kwoty:** waluta fikcyjna – tylko porównania względne (np. „rachunek ×1,2 względem Polski”).

- **Miejsce stałego przebywania (`_enr`)** to szacunek dostawcy, zmienny w czasie i pusty w dwóch oknach dat. Transakcje kart polskich bez niego są oznaczane jako „bez danych o pochodzeniu”.

- **Kod pocztowy → gmina:** jedna gmina na kod (największa powierzchnia); część kodów leży w kilku gminach, więc przy granicach możliwe pomyłki. Klucz to nazwa gminy, więc gminy o tej samej nazwie mogą się zlewać.

- **Handel internetowy** jest przypisany do siedziby firmy, a nie do miejsca zakupu, dlatego pomijany w ocenie lokalnego handlu.

- **Czas:** `000000` oznacza brak czasu i jest pomijany w rytmie dnia.

- **Korelacja, nie skutek:** wskaźniki pokazują istniejące zachowania, nie przewidują efektu połączenia gmin.


## 8. Jak rozszerzać

**Nowy temat w `app/marts.py`:** napisz `_build_<temat>(gmina_to_codes) -> dict` i dopisz do słownika `TOPICS`; plik `dataset/json/<temat>.json` powstanie przy pierwszym `ensure_topic`.

**Nowy temat w `build_marts.py`:** dodaj zestaw grupowania w `GROUPING SETS`, wyciągnij go w `split_tables`, a potem dopisz eksport w `export_json` i nazwę w `queries._TOPICS`. `--export-only` pozwala przebudować JSON bez skanowania.

**Nowa grupa kategorii:** dopisz nazwy `mrch_catg_nm` do `_GROUPS` w `categories.py` (i kolor w `_GROUP_COLORS` w `map_builder.py`, ikonę w `GROUP_ICONS`). Po zmianie przebuduj `t_*.json` i `by_category.json`.

**Zmiana progów oceny handlu:** stałe na górze `trade.py` (patrz 5.6). Wagi rankingu dopasowań są zapisane wprost w `matching_real.rank_matches` (0,8 / 0,2).


## 9. Znane niespójności i zalecenia

Poniższe punkty wynikają z lektury kodu; warto je rozstrzygnąć przed pokazaniem liczb z obu źródeł obok siebie.

| \# | Obserwacja | Skutek / zalecenie |
| - | - | - |
| 1 | **Dwa potoki liczą podobne rzeczy inaczej.** `build_marts.py`: tylko karty `CN`, bez ATM/gotówki, gmina = największa powierzchnia kodu, czas z uwzględnieniem DST, kupujący z `lau_enr`. `app/marts.py`: bez filtra segmentu (poza `residents`), odrzuca `000000`, mapowanie `dict(zip(Name, Gmina))` (ostatni wygrywa), godzina = GMT + 1 stałe. | Liczby z `summary`/`by_hour` nie zgadzają się z `t_*`. Zalecane: jeden potok i jedna funkcja mapowania kod → gmina. |
| 2 | `_build_summary` bierze `amt_median` z pierwszego kodu gminy (`rows[0]`), a `n_cards` sumuje karty unikalne per kod. | Mediana nie jest medianą gminy; liczba kart bywa zawyżona. |
| 3 | `by_category.json` nie jest generowany przez żaden przesłany skrypt. | Bez niego dopasowania używają fallbacku (`t_dominant` lub demo). Dodaj generator (np. z `t_structure`). |
| 4 | Trzy różne definicje „domu karty”: `analytics._get_b` (≥ 10 zakupów codziennych i ≥ 50% w jednym kodzie), `analytics.run_residents_analysis` i `marts._build_residents` (modalny `pstl_cd_enr` ≥ 50%), `build_marts.py` (`lau_enr` = gmina sprzedawcy). | Wskaźniki mieszkańców z różnych modułów nie są porównywalne. |
| 5 | `marts.py` liczy godzinę jako GMT + 1 zawsze; `build_marts.py` dodaje 2 h w czasie letnim. | Różnica jednej godziny latem między widokami. |
| 6 | `queries.py` zawiera zapytania z SQL składanym f-stringiem po nazwie miasta i po `pstl_cd_enr`. | Ryzyko błędów i wstrzyknięcia SQL; `get_stats_gmina` filtruje po kodzie kupującego (plan §14 zaleca `mrch_postal_code`). Usuń lub sparametryzuj. |
| 7 | `map_builder.build_map` bez danych dominujących koloruje gminy przez `hash(g) % N`. | `hash()` w Pythonie nie jest stabilny między uruchomieniami; kolory się zmieniają. |
| 8 | `streamlit_app.py` importuje `run_residents_analysis`, ale go nie używa; `charts.py` nie jest używany; docstring `2_Dopasowania_Gmin.py` mówi, że tryby są też na ekranie głównym, a `streamlit_app.py` ich nie renderuje. | Sprzątanie lub dopięcie funkcji. |
| 9 | `build_marts.py` wymaga kolumn `mrch_ctry_nm` i `transaction_type`, których nie używają pozostałe moduły (te filtrują po `mrch_ctry_cd`). | Sprawdź obecność kolumn w pełnym zbiorze. |
| 10 | `streamlit_app.load_marts()` wywołuje `ensure_topic("t_dominant")`, ale `t_dominant` nie jest w `marts.TOPICS`. | Działa tylko, gdy wcześniej uruchomiono `build_marts.py` (plik istnieje); inaczej `ValueError`. |



## 10. Szybki start

```
# 1. dane: dataset/datasprint_sample_data.parquet, geojson/postcodes_poland.geojson, assets/megapolis-visa.svg
# 2. tabele i tematy t_*
python build_marts.py
# 3. tematy summary, by_*, residents (albo wygenerują się przy pierwszym uruchomieniu aplikacji)
python -c "from app.marts import ensure_all; ensure_all()"
# 4. profile kategorii do dopasowań: dataset/json/by_category.json (patrz 4.3)
# 5. aplikacja
streamlit run streamlit_app.py
```

