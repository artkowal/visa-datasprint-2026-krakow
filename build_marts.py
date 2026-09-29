"""Buduje małe tabele zagregowane (poziom gminy) z surowego parquet – jednorazowo, offline.

    python build_marts.py                                   # sample (domyślnie)
    python build_marts.py --source dataset/datasprint_full_data.parquet

Jedno przejście po danych (GROUPING SETS). Uwzględnia: sprzedawca w Polsce, karty konsumenckie (CN),
bez gotówki/ATM. Kod pocztowy sprzedawcy jest mapowany na gminę (postal_gmina.parquet: gmina o największej
powierzchni kodu).

Typ kupującego (visitor), liczony dla każdej transakcji:
  zagr      karta wydana poza Polską
  mieszk    karta polska, lau_enr (szacowane miejsce stałego przebywania karty) = gmina sprzedawcy
  pl_gosc   karta polska, lau_enr = inna gmina
  nieznany  karta polska bez lau_enr (kolumny *_enr są puste w części okresu)

Wyniki:
  dataset/marts/g_*.parquet   pośrednie tabele na poziomie gminy (g_cat, g_pay, g_month, g_hour, g_country, g_card)
  dataset/marts/postal_gmina.parquet   mapowanie kod -> gmina
  dataset/json/t_*.json       tematy dla aplikacji (odczyt przez app.queries; format: {"cols": [...], "data": {gmina: [[...]]}}),
                              klucz "_PL" = suma dla całego kraju; _meta.json = źródło, pokrycie, okresy bez pochodzenia

    python build_marts.py --export-only    # tylko JSON z istniejących dataset/marts/g_*.parquet (bez skanowania)
"""
import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd

from app.categories import CATEGORY_TO_GROUP

GEOJSON = "geojson/postcodes_poland.geojson"
PREMIUM_CARDS = ("INFINITE", "PLATINUM", "PREMIER", "VISA SIGNATURE CARD")
NATIONAL = "_PL"
TOP_CATEGORIES = 15
TOP_COUNTRIES = 10


def build_postal_gmina(out: Path):
    gdf = gpd.read_file(GEOJSON)
    gdf["geometry"] = gdf["geometry"].make_valid()
    gdf["area"] = gdf.to_crs(2180).geometry.area
    per = gdf.groupby(["Name", "Gmina"], as_index=False)["area"].sum()
    per["n_gmin"] = per.groupby("Name")["Gmina"].transform("nunique")
    best = per.sort_values("area", ascending=False).drop_duplicates("Name")
    best = best.rename(columns={"Name": "postal", "Gmina": "gmina"})[["postal", "gmina", "n_gmin"]]
    best.to_parquet(out / "postal_gmina.parquet", index=False)
    return best


def aggregate(con: duckdb.DuckDBPyConnection, source: str) -> None:
    premium = ", ".join(f"'{c}'" for c in PREMIUM_CARDS)
    con.execute(f"""
        CREATE TEMP TABLE agg AS
        WITH src AS (
            SELECT
                regexp_replace(coalesce(mrch_postal_code, ''), '[^0-9]', '', 'g') AS dg,
                issr_ctry_nm, lau_enr, mrch_catg_nm, channel_flg, cp_flag, prch_mnth_id,
                prch_dt, tran_id_gmt_tm, crd_typ_nm, cs_tran_amt
            FROM read_parquet(?)
            WHERE mrch_ctry_nm = 'POLAND'
              AND prod_id_pltfrm_cd_vcis = 'CN'
              AND transaction_type <> 'ATM'
              AND channel_flg <> 'cash'
        ),
        b AS (
            SELECT
                coalesce(pg.gmina, '') AS gmina,
                CASE WHEN s.issr_ctry_nm <> 'POLAND' THEN 'zagr'
                     WHEN s.lau_enr IS NULL THEN 'nieznany'
                     WHEN upper(s.lau_enr) = pg.gmina THEN 'mieszk'
                     ELSE 'pl_gosc' END AS visitor,
                coalesce(s.mrch_catg_nm, '?') AS cat,
                coalesce(s.channel_flg, '?') AS ch,
                coalesce(s.cp_flag, -1)::INTEGER AS cp,
                coalesce(s.prch_mnth_id, -1)::INTEGER AS mon,
                -- czas polski z GMT (CET/CEST wg dat przejścia); brak czasu (000000) -> -1
                CASE WHEN s.tran_id_gmt_tm = '000000' OR s.tran_id_gmt_tm IS NULL THEN -1
                     ELSE (CAST(substr(s.tran_id_gmt_tm, 1, 2) AS INTEGER)
                           + CASE WHEN s.prch_dt BETWEEN '2025-03-30' AND '2025-10-25' THEN 2
                                  WHEN s.prch_dt >= '2026-03-29' THEN 2 ELSE 1 END) % 24 END AS hr,
                CASE WHEN s.tran_id_gmt_tm = '000000' OR s.tran_id_gmt_tm IS NULL THEN -1
                     ELSE dayofweek(CAST(s.prch_dt AS DATE)
                          + CASE WHEN CAST(substr(s.tran_id_gmt_tm, 1, 2) AS INTEGER)
                                      + CASE WHEN s.prch_dt BETWEEN '2025-03-30' AND '2025-10-25' THEN 2
                                             WHEN s.prch_dt >= '2026-03-29' THEN 2 ELSE 1 END >= 24
                                 THEN 1 ELSE 0 END) END AS dow,
                coalesce(s.issr_ctry_nm, '?') AS country,
                (s.crd_typ_nm IN ({premium})) AS prem,
                (pg.gmina IS NOT NULL) AS mapped,
                (length(s.dg) = 5) AS has_postal,
                s.cs_tran_amt AS amt
            FROM src s
            LEFT JOIN pg ON pg.postal = substr(s.dg, 1, 2) || '-' || substr(s.dg, 3, 3)
                        AND length(s.dg) = 5
        )
        SELECT gmina, visitor, cat, ch, cp, mon, hr, dow, country, prem, mapped, has_postal,
               count(*)::BIGINT AS n_tx, sum(amt)::DOUBLE AS amt
        FROM b
        GROUP BY GROUPING SETS (
            (gmina, visitor, cat),
            (gmina, visitor, ch, cp),
            (gmina, visitor, mon),
            (gmina, visitor, dow, hr),
            (gmina, country),
            (gmina, visitor, prem),
            (mapped, has_postal)
        )
    """, [source])


def split_tables(con: duckdb.DuckDBPyConnection, out: Path) -> dict:
    def copy(name: str, select: str, where: str) -> None:
        con.execute(f"COPY (SELECT {select} FROM agg WHERE gmina <> '' AND {where}) "
                    f"TO '{out / (name + '.parquet')}' (FORMAT parquet)")

    copy("g_cat", "gmina, visitor, cat, n_tx, amt", "cat IS NOT NULL AND visitor IS NOT NULL")
    copy("g_pay", "gmina, visitor, ch, cp, n_tx, amt", "ch IS NOT NULL AND visitor IS NOT NULL")
    copy("g_month", "gmina, visitor, mon, n_tx, amt", "mon IS NOT NULL AND visitor IS NOT NULL")
    copy("g_hour", "gmina, visitor, dow, hr, n_tx, amt", "hr IS NOT NULL AND visitor IS NOT NULL")
    copy("g_country", "gmina, country, n_tx, amt", "country IS NOT NULL AND visitor IS NULL AND country <> 'POLAND'")
    copy("g_card", "gmina, visitor, prem, n_tx, amt", "prem IS NOT NULL AND visitor IS NOT NULL")

    total, with_postal, mapped = (int(x or 0) for x in con.execute("""
        SELECT sum(n_tx), sum(n_tx) FILTER (has_postal), sum(n_tx) FILTER (mapped)
        FROM agg WHERE mapped IS NOT NULL AND gmina IS NULL""").fetchone())
    return {
        "tx_total": total,
        "tx_with_postal": with_postal,
        "tx_mapped_to_gmina": mapped,
        "pct_with_postal": round(100 * with_postal / total, 1) if total else None,
        "pct_mapped_to_gmina": round(100 * mapped / total, 1) if total else None,
    }


def origin_missing_months(con: duckdb.DuckDBPyConnection, out: Path) -> dict:
    """Miesiące, w których większość transakcji kartami polskimi nie ma lau_enr (puste kolumny *_enr)."""
    rows = con.execute(f"""
        SELECT mon,
               sum(n_tx) FILTER (visitor = 'nieznany') / sum(n_tx) FILTER (visitor <> 'zagr') AS unknown_share
        FROM read_parquet('{out / "g_month.parquet"}')
        GROUP BY mon ORDER BY mon
    """).fetchall()
    return {
        "unknown_origin_share_by_month": {int(m): round(float(s), 3) for m, s in rows if s is not None},
        "origin_missing_months": [int(m) for m, s in rows if s is not None and s > 0.5],
    }


def _by_gmina(rows: list[tuple]) -> dict[str, list[list]]:
    out: dict[str, list[list]] = {}
    for gmina, *rest in rows:
        out.setdefault(gmina, []).append(rest)
    return out


def _write_topic(json_dir: Path, name: str, cols: list[str], data: dict, extra: dict | None = None) -> None:
    payload = {"cols": cols, "data": data}
    if extra is not None:
        payload["extra"] = extra
    path = json_dir / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  ✓ {name}.json ({path.stat().st_size / 1024:.0f} KB)")


def export_json(marts: Path, json_dir: Path, meta: dict) -> None:
    """Zamienia tabele g_*.parquet na tematy JSON czytane przez aplikację (bez skanowania surowych danych)."""
    json_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.register("cat_map", pd.DataFrame({"cat": list(CATEGORY_TO_GROUP), "grupa": list(CATEGORY_TO_GROUP.values())}))
    t = lambda name: f"read_parquet('{marts / (name + '.parquet')}')"

    def national(sql_cols: str, table: str, group: str, extra_where: str = "") -> list[list]:
        return [list(r) for r in con.execute(
            f"SELECT {sql_cols} FROM {t(table)} {extra_where} GROUP BY {group} ORDER BY {group}").fetchall()]

    # struktura handlu: grupa x typ kupującego
    rows = con.execute(f"""
        SELECT c.gmina, coalesce(cm.grupa, 'Inne'), c.visitor, sum(c.n_tx)::BIGINT, round(sum(c.amt), 1)
        FROM {t('g_cat')} c LEFT JOIN cat_map cm ON cm.cat = c.cat GROUP BY 1, 2, 3""").fetchall()
    _write_topic(json_dir, "t_structure", ["grupa", "visitor", "n", "amt"], _by_gmina(rows))

    # najczęstsze kategorie z podziałem na kupujących
    rows = con.execute(f"""
        WITH a AS (
            SELECT c.gmina, c.cat, coalesce(cm.grupa, 'Inne') AS grupa,
                   sum(c.n_tx)::BIGINT AS n, sum(c.amt) / sum(c.n_tx) AS avg_amt,
                   coalesce(sum(c.n_tx) FILTER (visitor = 'mieszk'), 0)::BIGINT AS mieszk,
                   coalesce(sum(c.n_tx) FILTER (visitor = 'pl_gosc'), 0)::BIGINT AS pl_gosc,
                   coalesce(sum(c.n_tx) FILTER (visitor = 'zagr'), 0)::BIGINT AS zagr,
                   coalesce(sum(c.n_tx) FILTER (visitor = 'nieznany'), 0)::BIGINT AS nieznany
            FROM {t('g_cat')} c LEFT JOIN cat_map cm ON cm.cat = c.cat GROUP BY 1, 2, 3),
        r AS (SELECT *, row_number() OVER (PARTITION BY gmina ORDER BY n DESC) AS rk FROM a)
        SELECT gmina, cat, grupa, n, round(avg_amt, 1), mieszk, pl_gosc, zagr, nieznany FROM r WHERE rk <= {TOP_CATEGORIES}
        ORDER BY gmina, rk""").fetchall()
    _write_topic(json_dir, "t_categories", ["cat", "grupa", "n", "avg_amt", "mieszk", "pl_gosc", "zagr", "nieznany"], _by_gmina(rows))

    # kupujący
    data = _by_gmina(con.execute(f"SELECT gmina, visitor, sum(n_tx)::BIGINT, round(sum(amt), 1) FROM {t('g_cat')} GROUP BY 1, 2").fetchall())
    data[NATIONAL] = national("visitor, sum(n_tx)::BIGINT, round(sum(amt), 1)", "g_cat", "visitor")
    _write_topic(json_dir, "t_visitors", ["visitor", "n", "amt"], data)

    # płatności (kanał x cp_flag)
    data = _by_gmina(con.execute(f"SELECT gmina, visitor, ch, cp, sum(n_tx)::BIGINT FROM {t('g_pay')} GROUP BY 1, 2, 3, 4").fetchall())
    data[NATIONAL] = national("visitor, ch, cp, sum(n_tx)::BIGINT", "g_pay", "visitor, ch, cp")
    _write_topic(json_dir, "t_payments", ["visitor", "ch", "cp", "n"], data)

    # miesiące i rytm dnia
    _write_topic(json_dir, "t_months", ["visitor", "mon", "n"],
                 _by_gmina(con.execute(f"SELECT gmina, visitor, mon, sum(n_tx)::BIGINT FROM {t('g_month')} GROUP BY 1, 2, 3 ORDER BY 1, 3").fetchall()))
    _write_topic(json_dir, "t_hours", ["visitor", "dow", "hr", "n"],
                 _by_gmina(con.execute(f"SELECT gmina, visitor, dow, hr, sum(n_tx)::BIGINT FROM {t('g_hour')} GROUP BY 1, 2, 3, 4").fetchall()))

    # kraje wydania kart (top N + suma zagraniczna w "extra")
    rows = con.execute(f"""
        WITH a AS (SELECT gmina, country, sum(n_tx)::BIGINT AS n, sum(amt) / sum(n_tx) AS avg_amt FROM {t('g_country')} GROUP BY 1, 2),
        r AS (SELECT *, row_number() OVER (PARTITION BY gmina ORDER BY n DESC) AS rk FROM a)
        SELECT gmina, country, n, round(avg_amt, 1) FROM r WHERE rk <= {TOP_COUNTRIES} ORDER BY gmina, rk""").fetchall()
    totals = {g: int(n) for g, n in con.execute(f"SELECT gmina, sum(n_tx)::BIGINT FROM {t('g_country')} GROUP BY 1").fetchall()}
    _write_topic(json_dir, "t_countries", ["country", "n", "avg_amt"], _by_gmina(rows), extra={"foreign_total": totals})

    # typ karty (premium)
    data = _by_gmina(con.execute(f"SELECT gmina, visitor, prem, sum(n_tx)::BIGINT FROM {t('g_card')} GROUP BY 1, 2, 3").fetchall())
    data[NATIONAL] = national("visitor, prem, sum(n_tx)::BIGINT", "g_card", "visitor, prem")
    _write_topic(json_dir, "t_cards", ["visitor", "prem", "n"], data)

    # dominująca grupa kategorii per gmina (top 1 wg liczby transakcji)
    rows = con.execute(f"""
        WITH a AS (
            SELECT c.gmina, coalesce(cm.grupa, 'Inne') AS grupa,
                   sum(c.n_tx)::BIGINT AS n, round(sum(c.amt), 1) AS amt
            FROM {t('g_cat')} c LEFT JOIN cat_map cm ON cm.cat = c.cat GROUP BY 1, 2
        ),
        tot AS (SELECT gmina, sum(n) AS n_total FROM a GROUP BY 1),
        r AS (SELECT a.*, row_number() OVER (PARTITION BY a.gmina ORDER BY a.n DESC) AS rk FROM a)
        SELECT r.gmina, r.grupa, r.n, round(100.0 * r.n / tot.n_total, 1) AS pct, round(r.amt / r.n, 1) AS avg_amt
        FROM r JOIN tot ON r.gmina = tot.gmina WHERE r.rk = 1 ORDER BY r.gmina
    """).fetchall()
    _write_topic(json_dir, "t_dominant", ["grupa", "n", "pct", "avg_amt"],
                 {g: [[grp, n, pct, avg]] for g, grp, n, pct, avg in rows})

    (json_dir / "_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("JSON gotowy:", json_dir)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="dataset/datasprint_sample_data.parquet")
    ap.add_argument("--out", default="dataset/marts")
    ap.add_argument("--json-dir", default="dataset/json")
    ap.add_argument("--export-only", action="store_true", help="tylko JSON z istniejących g_*.parquet (bez skanowania)")
    ap.add_argument("--memory", default="5GB")
    ap.add_argument("--threads", type=int, default=3)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    json_dir = Path(args.json_dir)

    if args.export_only:
        meta = json.loads((out / "_meta.json").read_text(encoding="utf-8"))
        export_json(out, json_dir, meta)
        return

    con = duckdb.connect()
    con.execute(f"SET memory_limit='{args.memory}'")
    con.execute(f"SET threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET temp_directory='dataset/.duckdb_tmp'")

    pg = build_postal_gmina(out)
    con.register("pg", pg)
    print(f"postal_gmina: {len(pg)} kodów")

    aggregate(con, args.source)
    cov = split_tables(con, out)
    print("pokrycie:", cov)
    origin = origin_missing_months(con, out)
    print("miesiące bez pochodzenia:", origin["origin_missing_months"])

    meta = {
        "source": args.source,
        "source_kind": "full" if re.search(r"full", args.source) else "sample",
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "filters": "sprzedawca w Polsce, karty konsumenckie (CN), bez ATM/gotówki",
        **cov,
        **origin,
    }
    (out / "_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print("tabele gotowe:", out)
    export_json(out, json_dir, meta)


if __name__ == "__main__":
    main()
