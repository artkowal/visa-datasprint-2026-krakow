import re
from datetime import date
import polars as pl

SRC = "dataset/datasprint_sample_data.parquet"
PL_CODE = 616
DAILY_MCC = [5411, 5499, 5912, 5541, 5542, 5462, 5451, 5422]
MIN_HOME_TX, MIN_HOME_SHARE = 10, 0.5

# Okna bez danych pstl_cd_enr (wg statystyki.md)
_DEAD_WINDOWS = [
    (date(2026, 2, 28), date(2026, 3, 30)),
    (date(2026, 4, 30), date(2026, 6, 30)),
]

_SELECT = (
    "pymt_crd_acct_num_raw", "pstl_cd_enr", "mrch_postal_code",
    "issr_ctry_nm", "issr_jurn", "prod_id_pltfrm_cd_vcis", "cs_tran_amt",
    "crd_typ_nm", "channel_flg", "transaction_pos_entry_mode", "cp_flag",
    "mrch_ctry_cd", "mrch_catg_cd", "mrch_catg_nm",
    "tran_id_gmt_tm", "prch_dt", "prch_mnth_id",
)


def _collect(lf):
    try:
        return lf.collect(engine="streaming")
    except TypeError:
        return lf.collect(streaming=True)


def _prepare(lf: pl.LazyFrame) -> pl.LazyFrame:
    t = pl.col("tran_id_gmt_tm").cast(pl.Utf8).str.zfill(6)
    schema = lf.collect_schema()
    if schema["prch_dt"].is_numeric():
        date = pl.date(1899, 12, 30) + pl.duration(days=pl.col("prch_dt").cast(pl.Int64))
    elif schema["prch_dt"] == pl.String:
        date = pl.col("prch_dt").str.to_date()
    else:
        date = pl.col("prch_dt").cast(pl.Date)
    ts = (
        date.cast(pl.Datetime("us"))
        + pl.duration(
            hours=t.str.slice(0, 2).cast(pl.Int64),
            minutes=t.str.slice(2, 2).cast(pl.Int64),
            seconds=t.str.slice(4, 2).cast(pl.Int64),
        )
    ).dt.replace_time_zone("UTC").dt.convert_time_zone("Europe/Warsaw")

    return (
        lf.select(_SELECT)
        .filter(pl.col("mrch_ctry_cd").cast(pl.Int32) == PL_CODE)
        .with_columns(
            area=pl.col("mrch_postal_code").cast(pl.Utf8).str.strip_chars(),
            amt=pl.col("cs_tran_amt").cast(pl.Float64),
            month=pl.col("prch_mnth_id").cast(pl.Int32),
            dow=ts.dt.weekday(),
            hour=ts.dt.hour(),
            no_time=(t == "000000"),
            is_foreign=(pl.col("issr_jurn") != "Domestic"),
            is_business=pl.col("prod_id_pltfrm_cd_vcis").cast(pl.Utf8).is_in(["CO", "BZ", "GV"]),
            cp=(pl.col("cp_flag").cast(pl.Int8) == 1),
            mcc=pl.col("mrch_catg_cd").cast(pl.Int32, strict=False),
        )
        .with_columns(is_daily=pl.col("mcc").is_in(DAILY_MCC))
    )


def _money():
    a = pl.col("amt")
    return [
        pl.len().alias("n"),
        a.sum().alias("amt_sum"),
        a.median().alias("amt_median"),
        a.quantile(0.95).alias("amt_p95"),
    ]


def _get_a(df: pl.DataFrame) -> dict[str, pl.DataFrame]:
    main = df.filter(~pl.col("is_business"))
    foreign = main.filter(pl.col("is_foreign"))
    out: dict[str, pl.DataFrame] = {}

    out["A1_foreign_share"] = (
        main.group_by("area").agg(
            n=pl.len(),
            amt_sum=pl.col("amt").sum(),
            n_foreign=pl.col("is_foreign").sum(),
            amt_foreign=pl.col("amt").filter(pl.col("is_foreign")).sum(),
        )
        .with_columns(
            pct_foreign=(pl.col("n_foreign") / pl.col("n") * 100).round(1),
            pct_amt_foreign=(pl.col("amt_foreign") / pl.col("amt_sum") * 100).round(1),
        )
        .sort("n", descending=True)
    )

    if not foreign.is_empty():
        out["A2_top_countries"] = (
            foreign.group_by("issr_ctry_nm").agg(_money())
            .with_columns(pct=(pl.col("n") / pl.col("n").sum() * 100).round(1))
            .sort("n", descending=True)
            .head(10)
        )
        out["A5_card_tier"] = (
            foreign.group_by("crd_typ_nm").agg(_money())
            .with_columns(pct=(pl.col("n") / pl.col("n").sum() * 100).round(1))
            .sort("n", descending=True)
        )
        out["A6_by_month"] = (
            foreign.group_by("month")
            .agg(n=pl.len(), amt_sum=pl.col("amt").sum())
            .sort("month")
        )

    return out


def _get_c(df: pl.DataFrame) -> dict[str, pl.DataFrame]:
    main = df.filter(~pl.col("is_business"))
    timed = main.filter(~pl.col("no_time"))
    out: dict[str, pl.DataFrame] = {}

    heat = (
        timed.group_by("dow", "hour").agg(n=pl.len())
        .pivot(on="hour", index="dow", values="n")
        .sort("dow")
    )
    hour_cols = sorted((c for c in heat.columns if c != "dow"), key=int)
    out["C1_heatmap"] = heat.select("dow", *hour_cols).fill_null(0)

    out["C2_weekend"] = (
        main.group_by((pl.col("dow") >= 6).alias("is_weekend"))
        .agg(n=pl.len(), amt_sum=pl.col("amt").sum(), amt_median=pl.col("amt").median())
        .sort("is_weekend")
    )

    out["C3_foreign_hour"] = (
        timed.group_by("hour").agg(
            n=pl.len(),
            n_foreign=pl.col("is_foreign").sum(),
        )
        .with_columns(pct_foreign=(pl.col("n_foreign") / pl.col("n") * 100).round(1))
        .sort("hour")
    )

    out["C4_monthly"] = (
        main.group_by("month")
        .agg(
            n=pl.len(),
            amt_sum=pl.col("amt").sum(),
            amt_median=pl.col("amt").median(),
            n_foreign=pl.col("is_foreign").sum(),
        )
        .with_columns(pct_foreign=(pl.col("n_foreign") / pl.col("n") * 100).round(1))
        .sort("month")
    )

    return out


def _get_d(df: pl.DataFrame) -> dict[str, pl.DataFrame]:
    out: dict[str, pl.DataFrame] = {}
    q = [
        pl.len().alias("n"),
        pl.col("amt").median().alias("amt_median"),
        pl.col("amt").quantile(0.95).alias("amt_p95"),
        pl.col("amt").max().alias("amt_max"),
    ]
    out["D2_card_tier"] = df.group_by("crd_typ_nm").agg(q).sort("n", descending=True)
    out["D4_payment"] = (
        df.filter(~pl.col("is_business"))
        .group_by("channel_flg")
        .agg(n=pl.len(), amt_sum=pl.col("amt").sum())
        .with_columns(pct=(pl.col("n") / pl.col("n").sum() * 100).round(1))
        .sort("n", descending=True)
    )
    return out


def _get_b(base: pl.LazyFrame, sel_df: pl.DataFrame, pattern: str) -> dict[str, pl.DataFrame]:
    out: dict[str, pl.DataFrame] = {}
    dom = _collect(base.filter(~pl.col("is_business") & ~pl.col("is_foreign")))

    cnt = (
        dom.filter(pl.col("cp") & pl.col("is_daily") & pl.col("area").is_not_null())
        .group_by("pymt_crd_acct_num_raw", "area")
        .agg(n=pl.len())
    )
    home = _collect(
        cnt.group_by("pymt_crd_acct_num_raw").agg(
            daily_n=pl.col("n").sum(),
            home_area=pl.col("area").sort_by("n", descending=True).first(),
            home_n=pl.col("n").max(),
        )
        .filter(
            (pl.col("daily_n") >= MIN_HOME_TX)
            & (pl.col("home_n") / pl.col("daily_n") >= MIN_HOME_SHARE)
        )
        .select("pymt_crd_acct_num_raw", "home_area")
    )

    resident_cards = home.filter(pl.col("home_area").str.contains(pattern))
    if resident_cards.is_empty():
        return out

    agg = _collect(
        dom.lazy()
        .join(resident_cards.lazy(), on="pymt_crd_acct_num_raw")
        .group_by("home_area", "area", "mrch_catg_nm", "cp", "is_daily")
        .agg(n=pl.len(), amt=pl.col("amt").sum())
    )
    local = pl.col("area") == pl.col("home_area")
    cp = agg.filter(pl.col("cp"))

    out["B1_self_sufficiency"] = (
        cp.filter(pl.col("is_daily"))
        .group_by("home_area")
        .agg(n_daily=pl.col("n").sum(), n_local=pl.col("n").filter(local).sum())
        .with_columns(self_sufficiency=(pl.col("n_local") / pl.col("n_daily") * 100).round(1))
    )

    out["B2_outflow"] = (
        cp.filter(~local)
        .group_by("home_area", "area")
        .agg(n=pl.col("n").sum(), amt=pl.col("amt").sum())
        .with_columns(rank=pl.col("n").rank("ordinal", descending=True).over("home_area"))
        .filter(pl.col("rank") <= 5)
        .sort("home_area", "rank")
    )

    out["B4_outflow_category"] = (
        cp.group_by("home_area", "mrch_catg_nm")
        .agg(n=pl.col("n").sum(), n_local=pl.col("n").filter(local).sum())
        .with_columns(
            n_out=pl.col("n") - pl.col("n_local"),
            outflow_pct=((1 - pl.col("n_local") / pl.col("n")) * 100).round(1),
        )
        .with_columns(rank=pl.col("n_out").rank("ordinal", descending=True).over("home_area"))
        .filter(pl.col("rank") <= 10)
        .sort("home_area", "rank")
    )

    return out


def run_analysis(
    postal_codes: list[str],
    parquet: str = SRC,
    with_residents: bool = False,
) -> dict[str, pl.DataFrame]:
    pattern = "|".join(re.escape(c) for c in postal_codes)
    lf = pl.scan_parquet(parquet)
    base = _prepare(lf)
    sel = _collect(base.filter(pl.col("area").str.contains(pattern)))

    results: dict[str, pl.DataFrame] = {"_n_rows": sel.height}  # type: ignore
    results.update(_get_a(sel))
    results.update(_get_c(sel))
    results.update(_get_d(sel))
    if with_residents:
        results.update(_get_b(base, sel, pattern))

    return results


def run_residents_analysis(
    postal_codes: list[str],
    code_to_gmina: dict[str, str],
    parquet: str = SRC,
) -> dict:
    """
    Sekcje B + E — wymaga pełnego skanu (card_home z modalnego pstl_cd_enr).
    code_to_gmina: {kod_pocztowy: nazwa_gminy} dla całej Polski.
    """
    area_codes = set(postal_codes)
    lf = pl.scan_parquet(parquet)

    # ── card_home: modalny pstl_cd_enr z okresów z danymi ────────────────────
    schema = lf.collect_schema()
    if schema["prch_dt"].is_numeric():
        prch_dt_expr = (pl.date(1899, 12, 30) + pl.duration(days=pl.col("prch_dt").cast(pl.Int64)))
    elif schema["prch_dt"] == pl.String:
        prch_dt_expr = pl.col("prch_dt").str.to_date()
    else:
        prch_dt_expr = pl.col("prch_dt").cast(pl.Date)

    # Porównania dat muszą działać NA prch_dt już rzutowanym — with_columns idzie pierwsze.
    dead = [
        (pl.col("prch_dt") >= a) & (pl.col("prch_dt") <= b)
        for a, b in _DEAD_WINDOWS
    ]
    in_dead_window = dead[0]
    for d in dead[1:]:
        in_dead_window = in_dead_window | d

    home_lf = (
        lf.select("pymt_crd_acct_num_raw", "pstl_cd_enr", "prch_dt")
        .filter(pl.col("pstl_cd_enr").is_not_null())
        .with_columns(prch_dt_expr.alias("prch_dt"))
        .filter(~in_dead_window)
        .group_by("pymt_crd_acct_num_raw", "pstl_cd_enr")
        .agg(n=pl.len())
    )
    card_total = _collect(
        home_lf.group_by("pymt_crd_acct_num_raw").agg(total=pl.col("n").sum())
    )
    card_modal = _collect(
        home_lf.group_by("pymt_crd_acct_num_raw").agg(
            home_code=pl.col("pstl_cd_enr").sort_by("n", descending=True).first(),
            home_n=pl.col("n").max(),
        )
    )
    card_home = (
        card_modal.join(card_total, on="pymt_crd_acct_num_raw")
        .with_columns(confidence=(pl.col("home_n") / pl.col("total")).round(3))
        .filter(pl.col("confidence") >= 0.5)
        .select("pymt_crd_acct_num_raw", "home_code", "confidence")
    )

    # ── Przygotuj transakcje (tylko PL sprzedawcy, konsumenci) ───────────────
    base = _collect(
        _prepare(lf).filter(~pl.col("is_business") & ~pl.col("is_foreign"))
    )

    # dołącz card_home
    base = base.join(card_home, on="pymt_crd_acct_num_raw", how="left")

    # mapowanie kod → gmina
    mapping_df = pl.DataFrame({
        "code": list(code_to_gmina.keys()),
        "gmina": list(code_to_gmina.values()),
    })
    base = base.join(mapping_df.rename({"code": "home_code", "gmina": "home_gmina"}),
                     on="home_code", how="left")
    base = base.join(mapping_df.rename({"code": "area", "gmina": "area_gmina"}),
                     on="area", how="left")

    # ── Mieszkańcy obszaru (card_home w kodach pocztowych gminy) ─────────────
    residents = base.filter(pl.col("home_code").is_in(area_codes))
    n_resident_cards = residents["pymt_crd_acct_num_raw"].n_unique()

    out: dict = {"n_resident_cards": n_resident_cards}

    if residents.is_empty():
        return out

    is_local = pl.col("area").is_in(area_codes)

    # B1 — samowystarczalność (zakupy codzienne)
    daily = residents.filter(pl.col("cp") & pl.col("is_daily"))
    n_daily = len(daily)
    n_daily_local = daily.filter(is_local).height
    self_suff = round(n_daily_local / n_daily * 100, 1) if n_daily else 0
    out["B1_self_sufficiency"] = self_suff

    # B2 — odpływ: top gminy dokąd wyjeżdżają
    outflow = (
        residents.filter(pl.col("cp") & ~is_local & pl.col("area_gmina").is_not_null())
        .group_by("area_gmina")
        .agg(n=pl.len(), amt=pl.col("amt").sum())
        .sort("n", descending=True)
        .head(8)
        .to_pandas()
    )
    out["B2_outflow"] = outflow

    # B3 — napływ: skąd przyjeżdżają do obszaru
    inflow = (
        base.filter(
            pl.col("area").is_in(area_codes)
            & ~pl.col("home_code").is_in(area_codes)
            & pl.col("cp")
            & pl.col("home_gmina").is_not_null()
        )
        .group_by("home_gmina")
        .agg(n=pl.len(), amt=pl.col("amt").sum())
        .sort("n", descending=True)
        .head(8)
        .to_pandas()
    )
    out["B3_inflow"] = inflow

    # B4 — odpływ wg kategorii
    outflow_cat = (
        residents.filter(pl.col("cp") & ~is_local & pl.col("mrch_catg_nm").is_not_null())
        .group_by("mrch_catg_nm")
        .agg(n=pl.len())
        .sort("n", descending=True)
        .head(10)
        .to_pandas()
    )
    out["B4_outflow_cat"] = outflow_cat

    # ── E — wskaźniki syntetyczne ─────────────────────────────────────────────
    n_in  = int(inflow["n"].sum())  if len(inflow)  else 0
    n_out = int(outflow["n"].sum()) if len(outflow) else 0

    # E1: samowystarczalność (= B1)
    out["E1_self_sufficiency"] = self_suff

    # E2: indeks atrakcyjności = napływ / (napływ + odpływ)
    out["E2_attractiveness"] = round(n_in / (n_in + n_out) * 100, 1) if (n_in + n_out) else 0

    # E3: zależność od turystyki (% transakcji od gości w obszarze)
    area_tx = base.filter(pl.col("area").is_in(area_codes))
    n_area_total = len(area_tx)
    n_area_guests = area_tx.filter(~pl.col("home_code").is_in(area_codes)).height
    out["E3_tourism_dependency"] = round(n_area_guests / n_area_total * 100, 1) if n_area_total else 0

    # E5: siła powiązania z innymi gminami (suma napływ + odpływ per gmina)
    if len(outflow) and len(inflow):
        out_df = outflow.rename(columns={"area_gmina": "gmina", "n": "n_out", "amt": "amt_out"})
        in_df  = inflow.rename(columns={"home_gmina": "gmina", "n": "n_in",  "amt": "amt_in"})
        link = out_df.merge(in_df, on="gmina", how="outer").fillna(0)
        link["flow_total"] = link["n_out"] + link["n_in"]
        link["kierunek"] = link.apply(
            lambda r: "↔" if r["n_out"] > 0 and r["n_in"] > 0
            else ("→" if r["n_out"] > 0 else "←"), axis=1
        )
        out["E5_connections"] = link.sort_values("flow_total", ascending=False).head(8)

    return out
