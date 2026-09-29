"""
Mart loader — czyta pliki z dataset/json/*.json.
Jeśli plik nie istnieje, generuje go automatycznie.
Dodanie nowego tematu: zdefiniuj funkcję _build_<topic>() i dodaj do TOPICS.
"""

import json
from pathlib import Path
from typing import Callable

import duckdb
import geopandas as gpd

PARQUET   = "dataset/datasprint_sample_data.parquet"
GEOJSON   = "geojson/postcodes_poland.geojson"
JSON_DIR  = Path("dataset/json")
PL_CODE   = 616

# ── helpers ───────────────────────────────────────────────────────────────────

def _con():
    return duckdb.connect()

def _base_filter():
    return f"""
        FROM read_parquet('{PARQUET}')
        WHERE CAST(mrch_ctry_cd AS INTEGER) = {PL_CODE}
          AND mrch_postal_code IS NOT NULL
          AND CAST(tran_id_gmt_tm AS VARCHAR) != '000000'
    """

def _load_mapping() -> tuple[dict[str, str], dict[str, list[str]]]:
    """Zwraca (kod→gmina, gmina→[kody])."""
    gdf = gpd.read_file(GEOJSON)
    code_to_gmina = dict(zip(gdf["Name"], gdf["Gmina"]))
    gmina_to_codes: dict[str, list[str]] = {}
    for code, gmina in code_to_gmina.items():
        gmina_to_codes.setdefault(gmina, []).append(code)
    return code_to_gmina, gmina_to_codes

def _aggregate_to_gmina(
    df,
    code_col: str,
    gmina_to_codes: dict[str, list[str]],
    agg_fn: Callable,
) -> dict:
    """Grupuje DataFrame po gminie używając mapowania kod→gmina."""
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    df["_gmina"] = df[code_col].map(code_to_gmina)
    df = df.dropna(subset=["_gmina"])
    return agg_fn(df)

def _save(topic: str, data: dict):
    JSON_DIR.mkdir(parents=True, exist_ok=True)
    path = JSON_DIR / f"{topic}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    size = path.stat().st_size / 1024
    print(f"  ✓ {topic}.json ({size:.0f} KB)")

# ── builders — jeden per temat ────────────────────────────────────────────────

def _build_summary(gmina_to_codes: dict) -> dict:
    con = _con()
    df = con.execute(f"""
        SELECT
            TRIM(mrch_postal_code)                                         AS code,
            COUNT(*)                                                        AS n_total,
            COUNT(DISTINCT pymt_crd_acct_num_raw)                          AS n_cards,
            SUM(CASE WHEN issr_jurn != 'Domestic' THEN 1 ELSE 0 END)      AS n_foreign,
            SUM(CASE WHEN issr_jurn  = 'Domestic' THEN 1 ELSE 0 END)      AS n_domestic,
            ROUND(MEDIAN(cs_tran_amt), 2)                                  AS amt_median,
            ROUND(QUANTILE_CONT(cs_tran_amt, 0.95), 2)                    AS amt_p95,
            ROUND(SUM(cs_tran_amt), 2)                                     AS amt_sum
        {_base_filter()}
        GROUP BY TRIM(mrch_postal_code)
    """).df()
    con.close()

    idx = df.set_index("code").to_dict("index")
    out = {}
    for gmina, codes in gmina_to_codes.items():
        rows = [idx[c] for c in codes if c in idx]
        if not rows:
            continue
        n_total   = sum(r["n_total"]   for r in rows)
        n_foreign = sum(r["n_foreign"] for r in rows)
        out[gmina] = {
            "n_total":    int(n_total),
            "n_cards":    int(sum(r["n_cards"]   for r in rows)),
            "n_foreign":  int(n_foreign),
            "n_domestic": int(sum(r["n_domestic"] for r in rows)),
            "pct_foreign": round(n_foreign / n_total * 100, 1) if n_total else 0,
            "amt_median": float(rows[0]["amt_median"]),
            "amt_sum":    round(sum(r["amt_sum"] for r in rows), 2),
        }
    return out


def _build_by_country(gmina_to_codes: dict) -> dict:
    con = _con()
    df = con.execute(f"""
        SELECT
            TRIM(mrch_postal_code) AS code,
            issr_ctry_nm           AS country,
            COUNT(*)               AS n,
            ROUND(MEDIAN(cs_tran_amt), 2) AS amt_median
        {_base_filter()}
          AND issr_jurn != 'Domestic'
        GROUP BY code, country
    """).df()
    con.close()

    from collections import defaultdict
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    df["gmina"] = df["code"].map(code_to_gmina)
    df = df.dropna(subset=["gmina"])

    agg: dict[str, dict] = defaultdict(lambda: defaultdict(float))
    for row in df.itertuples(index=False):
        agg[row.gmina][row.country] += row.n

    out = {}
    for gmina, country_counts in agg.items():
        total = sum(country_counts.values())
        out[gmina] = [
            {"country": c, "n": int(n), "pct": round(n / total * 100, 1)}
            for c, n in sorted(country_counts.items(), key=lambda x: -x[1])[:10]
        ]
    return out


def _build_by_month(gmina_to_codes: dict) -> dict:
    con = _con()
    df = con.execute(f"""
        SELECT
            TRIM(mrch_postal_code)                                     AS code,
            CAST(prch_mnth_id AS INTEGER)                              AS month,
            COUNT(*)                                                   AS n,
            SUM(CASE WHEN issr_jurn != 'Domestic' THEN 1 ELSE 0 END)  AS n_foreign
        {_base_filter()}
        GROUP BY code, month
    """).df()
    con.close()

    from collections import defaultdict
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    df["gmina"] = df["code"].map(code_to_gmina)
    df = df.dropna(subset=["gmina"])

    agg: dict = defaultdict(lambda: defaultdict(lambda: {"n": 0, "n_foreign": 0}))
    for row in df.itertuples(index=False):
        agg[row.gmina][row.month]["n"]         += row.n
        agg[row.gmina][row.month]["n_foreign"] += row.n_foreign

    out = {}
    for gmina, months in agg.items():
        out[gmina] = sorted([
            {"month": m, "n": int(v["n"]), "n_foreign": int(v["n_foreign"]),
             "pct_foreign": round(v["n_foreign"] / v["n"] * 100, 1) if v["n"] else 0}
            for m, v in months.items()
        ], key=lambda x: x["month"])
    return out


def _build_by_hour(gmina_to_codes: dict) -> dict:
    con = _con()
    df = con.execute(f"""
        SELECT
            TRIM(mrch_postal_code) AS code,
            (CAST(LEFT(LPAD(CAST(tran_id_gmt_tm AS VARCHAR),6,'0'),2) AS INTEGER)+1) % 24 AS hour_pl,
            COUNT(*) AS n,
            SUM(CASE WHEN issr_jurn != 'Domestic' THEN 1 ELSE 0 END) AS n_foreign
        {_base_filter()}
        GROUP BY code, hour_pl
    """).df()
    con.close()

    from collections import defaultdict
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    df["gmina"] = df["code"].map(code_to_gmina)
    df = df.dropna(subset=["gmina"])

    agg: dict = defaultdict(lambda: defaultdict(lambda: {"n": 0, "n_foreign": 0}))
    for row in df.itertuples(index=False):
        agg[row.gmina][row.hour_pl]["n"]         += row.n
        agg[row.gmina][row.hour_pl]["n_foreign"] += row.n_foreign

    out = {}
    for gmina, hours in agg.items():
        out[gmina] = sorted([
            {"hour": h, "n": int(v["n"]), "n_foreign": int(v["n_foreign"]),
             "pct_foreign": round(v["n_foreign"] / v["n"] * 100, 1) if v["n"] else 0}
            for h, v in hours.items()
        ], key=lambda x: x["hour"])
    return out


def _build_by_card(gmina_to_codes: dict) -> dict:
    con = _con()
    df = con.execute(f"""
        SELECT
            TRIM(mrch_postal_code)        AS code,
            COALESCE(crd_typ_nm, '?')     AS card_type,
            COUNT(*)                      AS n,
            ROUND(MEDIAN(cs_tran_amt), 2) AS amt_median
        {_base_filter()}
        GROUP BY code, card_type
    """).df()
    con.close()

    from collections import defaultdict
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    df["gmina"] = df["code"].map(code_to_gmina)
    df = df.dropna(subset=["gmina"])

    agg: dict = defaultdict(lambda: defaultdict(float))
    for row in df.itertuples(index=False):
        agg[row.gmina][row.card_type] += row.n

    out = {}
    for gmina, counts in agg.items():
        total = sum(counts.values())
        out[gmina] = [
            {"type": t, "n": int(n), "pct": round(n / total * 100, 1)}
            for t, n in sorted(counts.items(), key=lambda x: -x[1])
        ]
    return out


def _build_by_channel(gmina_to_codes: dict) -> dict:
    con = _con()
    df = con.execute(f"""
        SELECT
            TRIM(mrch_postal_code)        AS code,
            COALESCE(channel_flg, '?')    AS channel,
            COUNT(*)                      AS n
        {_base_filter()}
        GROUP BY code, channel
    """).df()
    con.close()

    from collections import defaultdict
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    df["gmina"] = df["code"].map(code_to_gmina)
    df = df.dropna(subset=["gmina"])

    agg: dict = defaultdict(lambda: defaultdict(float))
    for row in df.itertuples(index=False):
        agg[row.gmina][row.channel] += row.n

    out = {}
    for gmina, counts in agg.items():
        total = sum(counts.values())
        out[gmina] = [
            {"channel": ch, "n": int(n), "pct": round(n / total * 100, 1)}
            for ch, n in sorted(counts.items(), key=lambda x: -x[1])
        ]
    return out


def _build_residents(gmina_to_codes: dict) -> dict:
    """
    Sekcje B + E dla wszystkich gmin — DuckDB streaming (nie ładuje do RAM).
    Zapisuje {gmina: {n_resident_cards, B1..B4, E1..E5}}.
    """
    import pandas as pd
    from collections import defaultdict

    DAILY_MCC = [5411, 5499, 5912, 5541, 5542, 5462, 5451, 5422]
    daily_mcc_str = ",".join(str(m) for m in DAILY_MCC)

    con = _con()

    # Mała tabela mapowania kod → gmina (≈ 30k wierszy, mieści się w RAM)
    code_to_gmina = {c: g for g, codes in gmina_to_codes.items() for c in codes}
    mapping_pd = pd.DataFrame({
        "code":  list(code_to_gmina.keys()),
        "gmina": list(code_to_gmina.values()),
    })
    con.register("_gmina_map_pd", mapping_pd)
    con.execute("CREATE TEMP TABLE gmina_map AS SELECT * FROM _gmina_map_pd")

    # Wykryj typ kolumny prch_dt (może być liczbą — dni od 1899-12-30)
    type_row = con.execute(
        f"SELECT typeof(prch_dt) FROM read_parquet('{PARQUET}') LIMIT 1"
    ).fetchone()
    prch_dt_type = (type_row[0] if type_row else "DATE").upper()
    if any(t in prch_dt_type for t in ("INT", "DOUBLE", "FLOAT", "DECIMAL", "HUGEINT", "BIGINT")):
        date_expr = "(DATE '1899-12-30' + CAST(prch_dt AS INTEGER))"
    else:
        date_expr = "TRY_CAST(prch_dt AS DATE)"

    # ── Skan 1: card_home (modal pstl_cd_enr ≥ 50%) ──────────────────────────
    print("  Skan 1/2: card_home…")
    con.execute(f"""
        CREATE TEMP TABLE card_home AS
        WITH code_counts AS (
            SELECT
                pymt_crd_acct_num_raw,
                pstl_cd_enr,
                COUNT(*) AS cnt
            FROM read_parquet('{PARQUET}')
            WHERE pstl_cd_enr IS NOT NULL
              AND {date_expr} NOT BETWEEN DATE '2026-02-28' AND DATE '2026-03-30'
              AND {date_expr} NOT BETWEEN DATE '2026-04-30' AND DATE '2026-06-30'
            GROUP BY pymt_crd_acct_num_raw, pstl_cd_enr
        ),
        card_totals AS (
            SELECT pymt_crd_acct_num_raw, SUM(cnt) AS total_cnt
            FROM code_counts
            GROUP BY pymt_crd_acct_num_raw
        )
        SELECT
            cc.pymt_crd_acct_num_raw,
            arg_max(cc.pstl_cd_enr, cc.cnt) AS home_code,
            gm.gmina                         AS home_gmina
        FROM code_counts cc
        JOIN card_totals ct USING (pymt_crd_acct_num_raw)
        LEFT JOIN gmina_map gm ON gm.code = cc.pstl_cd_enr
        WHERE cc.cnt * 1.0 / ct.total_cnt >= 0.5
          AND gm.gmina IS NOT NULL
        GROUP BY cc.pymt_crd_acct_num_raw, gm.gmina
    """)
    n_ch = con.execute("SELECT COUNT(*) FROM card_home").fetchone()[0]
    print(f"    → {n_ch:,} kart z przypisaną gminą")

    # ── Skan 2: CP przepływy (domestic consumer, CP) ──────────────────────────
    # DuckDB hash-join: card_home (~n_ch wierszy) jako prawa strona w RAM,
    # parquet skanowany strumieniowo — nie ładuje 305M wierszy naraz.
    print("  Skan 2/2: przepływy CP…")
    con.execute(f"""
        CREATE TEMP TABLE cp_flows AS
        SELECT
            ch.home_gmina,
            gm_a.gmina                           AS area_gmina,
            CAST(t.mrch_catg_nm AS VARCHAR)       AS mrch_catg_nm,
            TRY_CAST(t.mrch_catg_cd AS INTEGER)   AS mrch_catg_cd,
            COUNT(*)                              AS n
        FROM read_parquet('{PARQUET}') t
        JOIN card_home ch ON ch.pymt_crd_acct_num_raw = t.pymt_crd_acct_num_raw
        LEFT JOIN gmina_map gm_a
               ON gm_a.code = TRIM(CAST(t.mrch_postal_code AS VARCHAR))
        WHERE CAST(t.mrch_ctry_cd AS INTEGER) = {PL_CODE}
          AND t.mrch_postal_code IS NOT NULL
          AND CAST(t.prod_id_pltfrm_cd_vcis AS VARCHAR) NOT IN ('CO', 'BZ', 'GV')
          AND t.issr_jurn = 'Domestic'
          AND CAST(t.cp_flag AS INTEGER) = 1
          AND gm_a.gmina IS NOT NULL
        GROUP BY ch.home_gmina, gm_a.gmina, mrch_catg_nm, mrch_catg_cd
    """)

    # ── Agregacje (wszystkie małe, mieszczą się w RAM) ────────────────────────
    print("  Agregacja metryk…")

    n_cards_df = con.execute(
        "SELECT home_gmina, COUNT(*) AS n_cards FROM card_home GROUP BY home_gmina"
    ).df()

    b1_df = con.execute(f"""
        SELECT
            home_gmina,
            ROUND(
                SUM(CASE WHEN area_gmina = home_gmina THEN n ELSE 0 END) * 100.0
                / NULLIF(SUM(n), 0), 1
            ) AS B1
        FROM cp_flows
        WHERE mrch_catg_cd IN ({daily_mcc_str})
        GROUP BY home_gmina
    """).df()

    # outflow: wiersze (home → area, różne gminy), posortowane malejąco
    out_df = con.execute("""
        SELECT home_gmina, area_gmina, SUM(n) AS n
        FROM cp_flows
        WHERE area_gmina != home_gmina
        GROUP BY home_gmina, area_gmina
        ORDER BY home_gmina, n DESC
    """).df()

    # całkowity outflow + inflow per gmina (do E2 bez obcinania top-8)
    total_out_df = con.execute("""
        SELECT home_gmina AS gmina, SUM(n) AS n_out
        FROM cp_flows WHERE area_gmina != home_gmina
        GROUP BY home_gmina
    """).df()
    total_in_df = con.execute("""
        SELECT area_gmina AS gmina, SUM(n) AS n_in
        FROM cp_flows WHERE area_gmina != home_gmina
        GROUP BY area_gmina
    """).df()

    # E3: zależność od gości
    e3_df = con.execute("""
        SELECT
            area_gmina,
            ROUND(
                SUM(CASE WHEN area_gmina != home_gmina THEN n ELSE 0 END) * 100.0
                / NULLIF(SUM(n), 0), 1
            ) AS E3
        FROM cp_flows
        GROUP BY area_gmina
    """).df()

    # B4: odpływ wg kategorii (top 10 per gmina)
    b4_df = con.execute("""
        SELECT home_gmina, mrch_catg_nm, SUM(n) AS n
        FROM cp_flows
        WHERE area_gmina != home_gmina AND mrch_catg_nm IS NOT NULL
        GROUP BY home_gmina, mrch_catg_nm
        ORDER BY home_gmina, n DESC
    """).df()

    con.close()

    # ── Konwersja do słowników Python ─────────────────────────────────────────
    n_cards_d  = dict(zip(n_cards_df["home_gmina"], n_cards_df["n_cards"].astype(int)))
    b1_d       = dict(zip(b1_df["home_gmina"], b1_df["B1"].fillna(0).astype(float)))
    e3_d       = dict(zip(e3_df["area_gmina"], e3_df["E3"].fillna(0).astype(float)))
    total_out_d = dict(zip(total_out_df["gmina"], total_out_df["n_out"].astype(int)))
    total_in_d  = dict(zip(total_in_df["gmina"],  total_in_df["n_in"].astype(int)))

    # outflow top-8 per home_gmina
    outflow_d: dict = defaultdict(list)
    for r in out_df.itertuples(index=False):
        if len(outflow_d[r.home_gmina]) < 8:
            outflow_d[r.home_gmina].append({"area_gmina": r.area_gmina, "n": int(r.n)})

    # inflow top-8 per area_gmina (globalnie posortowane malejąco po n)
    inflow_d: dict = defaultdict(list)
    for r in out_df.sort_values("n", ascending=False).itertuples(index=False):
        if len(inflow_d[r.area_gmina]) < 8:
            inflow_d[r.area_gmina].append({"home_gmina": r.home_gmina, "n": int(r.n)})

    # B4 top-10 per home_gmina
    b4_d: dict = defaultdict(list)
    for r in b4_df.itertuples(index=False):
        if len(b4_d[r.home_gmina]) < 10:
            b4_d[r.home_gmina].append({"mrch_catg_nm": r.mrch_catg_nm, "n": int(r.n)})

    out = {}
    for gmina in gmina_to_codes:
        nc = int(n_cards_d.get(gmina, 0))
        if nc == 0:
            continue
        b1    = float(b1_d.get(gmina, 0.0))
        n_out = int(total_out_d.get(gmina, 0))
        n_in  = int(total_in_d.get(gmina, 0))
        out_map = {r["area_gmina"]: r["n"] for r in outflow_d.get(gmina, [])}
        in_map  = {r["home_gmina"]: r["n"] for r in inflow_d.get(gmina, [])}
        e5 = sorted([
            {
                "gmina": g,
                "kierunek": "↔" if out_map.get(g, 0) > 0 and in_map.get(g, 0) > 0
                            else ("→" if out_map.get(g, 0) > 0 else "←"),
                "n_out": out_map.get(g, 0),
                "n_in":  in_map.get(g, 0),
                "flow_total": out_map.get(g, 0) + in_map.get(g, 0),
            }
            for g in set(out_map) | set(in_map)
        ], key=lambda x: -x["flow_total"])[:8]
        out[gmina] = {
            "n_resident_cards":      nc,
            "B1_self_sufficiency":   b1,
            "B2_outflow":            outflow_d.get(gmina, []),
            "B3_inflow":             inflow_d.get(gmina, []),
            "B4_outflow_cat":        b4_d.get(gmina, []),
            "E1_self_sufficiency":   b1,
            "E2_attractiveness":     round(n_in / (n_in + n_out) * 100, 1) if (n_in + n_out) else 0,
            "E3_tourism_dependency": float(e3_d.get(gmina, 0.0)),
            "E5_connections":        e5,
        }
    return out


# ── rejestr tematów ───────────────────────────────────────────────────────────

TOPICS: dict[str, Callable] = {
    "summary":    _build_summary,
    "by_country": _build_by_country,
    "by_month":   _build_by_month,
    "by_hour":    _build_by_hour,
    "by_card":    _build_by_card,
    "by_channel": _build_by_channel,
    "residents":  _build_residents,
}

# ── publiczne API ─────────────────────────────────────────────────────────────

def ensure_topic(topic: str) -> dict:
    """Zwraca dane dla tematu. Generuje plik jeśli nie istnieje."""
    path = JSON_DIR / f"{topic}.json"
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    if topic not in TOPICS:
        raise ValueError(f"Nieznany temat: {topic}. Dostępne: {list(TOPICS)}")

    print(f"Generuję {topic}.json…")
    _, gmina_to_codes = _load_mapping()
    data = TOPICS[topic](gmina_to_codes)
    _save(topic, data)
    return data


def ensure_all():
    """Generuje wszystkie brakujące pliki."""
    _, gmina_to_codes = _load_mapping()
    for topic, builder in TOPICS.items():
        path = JSON_DIR / f"{topic}.json"
        if not path.exists():
            print(f"Generuję {topic}.json…")
            data = builder(gmina_to_codes)
            _save(topic, data)
        else:
            print(f"  → {topic}.json już istnieje, pomijam")


def get_gmina(gmina: str, *topics: str) -> dict:
    """Zwraca wszystkie dane dla jednej gminy ze wskazanych tematów."""
    out = {}
    for topic in topics:
        data = ensure_topic(topic)
        out[topic] = data.get(gmina, {})
    return out
