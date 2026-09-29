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


# ── rejestr tematów ───────────────────────────────────────────────────────────

TOPICS: dict[str, Callable] = {
    "summary":    _build_summary,
    "by_country": _build_by_country,
    "by_month":   _build_by_month,
    "by_hour":    _build_by_hour,
    "by_card":    _build_by_card,
    "by_channel": _build_by_channel,
    # "residents":   _build_residents,   # TODO — B section
    # "connections": _build_connections, # TODO — E section
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
