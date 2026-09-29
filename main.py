import pathlib
import re

import polars as pl

SRC = "dataset/datasprint_sample_data.parquet"
OUT_DIR = pathlib.Path("dataset/selected_area")
PL_CODE = 616
DAILY_MCC = [5411, 5499, 5912, 5541, 5542, 5462, 5451, 5422]  # spożywcze, apteki, paliwo, piekarnie
MIN_HOME_TX, MIN_HOME_SHARE = 10, 0.5

select_cols = (
    'pymt_crd_acct_num_raw', 'pstl_cd_enr', 'mrch_postal_code', 'mrch_city_nm_raw',
    'issr_ctry_nm', 'issr_jurn', 'prod_id_pltfrm_cd_vcis', 'cs_tran_amt',
    'crd_typ_nm', 'channel_flg', 'transaction_pos_entry_mode', 'cp_flag',
    'mrch_ctry_cd', 'mrch_catg_cd', 'mrch_catg_nm',
    'tran_id_gmt_tm', 'prch_dt', 'prch_mnth_id',
)


def collect(lf):
    try:
        return lf.collect(engine="streaming")
    except TypeError:  # starsze wersje polars
        return lf.collect(streaming=True)


def show(name, df, n=None):
    """Wypisuje tabelę i zapisuje ją do CSV."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.write_csv(OUT_DIR / f"{name}.csv")
    print(f"\n=== {name} ({df.height} wierszy) ===")
    print(df if n is None else df.head(n))


def ask_input():
    raw = input("Enter postal codes separated by commas (e.g. 33-152, 33-100): ")
    codes = [c.strip() for c in raw.split(",") if c.strip()]
    if not codes:
        raise ValueError("No postal codes provided.")

    print("\nCo oznacza obszar?\n"
          "  1 = transakcje zrobione w tych kodach (mrch_postal_code)  [zalecane, widać turystów]\n"
          "  2 = karty przypisane do tych kodów (pstl_cd_enr)          [brak kart zagranicznych]")
    mode = input("Wybór [1]: ").strip() or "1"
    if mode not in ("1", "2"):
        raise ValueError("Wybierz 1 lub 2.")

    with_b = input("Policzyć też B (mieszkańcy)? Wymaga przejścia całego pliku [t/N]: ").strip().lower() == "t"
    return codes, ("mrch_postal_code" if mode == "1" else "pstl_cd_enr"), with_b


def prepare(lf):
    """Czyszczenie, czas polski, flagi. Tylko polscy sprzedawcy."""
    t = pl.col("tran_id_gmt_tm").cast(pl.Utf8).str.zfill(6)
    if lf.collect_schema()["prch_dt"].is_numeric():  # serial Excela
        date = pl.date(1899, 12, 30) + pl.duration(days=pl.col("prch_dt").cast(pl.Int64))
    else:
        date = pl.col("prch_dt").cast(pl.Date)
    ts = (date.cast(pl.Datetime("us"))
          + pl.duration(hours=t.str.slice(0, 2).cast(pl.Int64),
                        minutes=t.str.slice(2, 2).cast(pl.Int64),
                        seconds=t.str.slice(4, 2).cast(pl.Int64))
          ).dt.replace_time_zone("UTC").dt.convert_time_zone("Europe/Warsaw")
    crd = pl.col("crd_typ_nm").cast(pl.Utf8)

    return (
        lf.select(select_cols)
        .filter(pl.col("mrch_ctry_cd").cast(pl.Int32) == PL_CODE)
        .with_columns(
            area=pl.col("mrch_postal_code").cast(pl.Utf8).str.strip_chars(),
            amt=pl.col("cs_tran_amt").cast(pl.Float64),
            month=pl.col("prch_mnth_id").cast(pl.Int32),
            dow=ts.dt.weekday(),  # 1 = pn ... 7 = nd
            hour=ts.dt.hour(),    # czas polski
            no_time=(t == "000000"),
            is_foreign=(pl.col("issr_jurn") != "Domestic"),
            is_business=crd.str.to_uppercase().str.contains("BUSINESS"),
            cp=(pl.col("cp_flag").cast(pl.Int8) == 1),
            mcc=pl.col("mrch_catg_cd").cast(pl.Int32, strict=False),
        )
        .with_columns(is_daily=pl.col("mcc").is_in(DAILY_MCC))
    )


def money():
    a = pl.col("amt")
    return [pl.len().alias("n"), a.sum().alias("amt_sum"), a.median().alias("amt_median"),
            a.quantile(0.95).alias("amt_p95")]


# ------------------------------------------------------------------ A
def stats_a(df):
    print("\n########## A. TURYŚCI I GOŚCIE ##########")
    main = df.filter(~pl.col("is_business"))
    foreign = main.filter(pl.col("is_foreign"))

    show("A1_foreign_share", main.group_by("area").agg(
        n=pl.len(), amt_sum=pl.col("amt").sum(),
        n_foreign=pl.col("is_foreign").sum(),
        amt_foreign=pl.col("amt").filter(pl.col("is_foreign")).sum(),
    ).with_columns(
        share_n_foreign=(pl.col("n_foreign") / pl.col("n")).round(4),
        share_amt_foreign=(pl.col("amt_foreign") / pl.col("amt_sum")).round(4),
    ).sort("n", descending=True))

    if foreign.is_empty():
        print("\nBrak kart zagranicznych w tym wycinku (przy trybie 2 to oczekiwane).")
        return

    show("A2_top10_countries", foreign.group_by("issr_ctry_nm").agg(money())
         .with_columns(share_n=(pl.col("n") / pl.col("n").sum()).round(4))
         .sort("n", descending=True), n=10)
    show("A5_card_tier_of_guests", foreign.group_by("crd_typ_nm").agg(money())
         .with_columns(share_n=(pl.col("n") / pl.col("n").sum()).round(4)).sort("n", descending=True))
    show("A6_foreign_by_month", foreign.group_by("month").agg(
        n=pl.len(), amt_sum=pl.col("amt").sum()).sort("month"))


# ------------------------------------------------------------------ C
def stats_c(df):
    print("\n########## C. CZAS I RYTM DNIA ##########")
    main = df.filter(~pl.col("is_business"))
    timed = main.filter(~pl.col("no_time"))
    print(f"\nOdrzucono {main.height - timed.height:,} wierszy z czasem 000000 "
          f"({(main.height - timed.height) / max(main.height, 1):.1%})")

    heat = timed.group_by("dow", "hour").agg(n=pl.len()).pivot(on="hour", index="dow", values="n").sort("dow")
    hour_cols = sorted((c for c in heat.columns if c != "dow"), key=int)
    show("C1_heatmap_dow_x_hour", heat.select("dow", *hour_cols).fill_null(0))

    by_hour = timed.group_by("hour").agg(
        n=pl.len(), n_foreign=pl.col("is_foreign").sum()
    ).with_columns(foreign_share=(pl.col("n_foreign") / pl.col("n")).round(4)).sort("hour")
    show("C3_foreign_share_by_hour", by_hour)

    show("C2_weekend_vs_weekday", main.group_by((pl.col("dow") >= 6).alias("is_weekend")).agg(
        n=pl.len(), amt_sum=pl.col("amt").sum(), amt_median=pl.col("amt").median()).sort("is_weekend"))
    show("C4_monthly_trend", main.group_by("month").agg(
        n=pl.len(), amt_sum=pl.col("amt").sum(), amt_median=pl.col("amt").median()).sort("month"))


# ------------------------------------------------------------------ D
def stats_d(df):
    print("\n########## D. WARTOŚĆ I SEGMENTACJA ##########")
    q = [pl.len().alias("n"), pl.col("amt").mean().alias("amt_mean"), pl.col("amt").median().alias("amt_median"),
         pl.col("amt").quantile(0.90).alias("amt_p90"), pl.col("amt").quantile(0.95).alias("amt_p95"),
         pl.col("amt").quantile(0.99).alias("amt_p99"), pl.col("amt").max().alias("amt_max")]
    show("D1_amount_distribution", df.group_by("is_business").agg(q))
    show("D2_card_tier_vs_amount", df.group_by("crd_typ_nm").agg(q).sort("n", descending=True))
    show("D2_segment_vs_amount", df.group_by("prod_id_pltfrm_cd_vcis").agg(q).sort("n", descending=True))
    show("D4_payment_methods", df.filter(~pl.col("is_business"))
         .group_by("channel_flg", "transaction_pos_entry_mode").agg(n=pl.len(), amt_sum=pl.col("amt").sum())
         .with_columns(share_n=(pl.col("n") / pl.col("n").sum()).round(4)).sort("n", descending=True))


# ------------------------------------------------------------------ B
def stats_b(base, sel_df, pattern):
    """Mieszkańcy: kod domowy karty z heurystyki (>=10 transakcji codziennych i >=50% w jednym kodzie)."""
    print("\n########## B. MIESZKAŃCY (kod domowy z heurystyki) ##########")
    dom = base.filter(~pl.col("is_business") & ~pl.col("is_foreign"))
    cnt = (dom.filter(pl.col("cp") & pl.col("is_daily") & pl.col("area").is_not_null())
           .group_by("pymt_crd_acct_num_raw", "area").agg(n=pl.len()))
    home = collect(
        cnt.group_by("pymt_crd_acct_num_raw").agg(
            daily_n=pl.col("n").sum(),
            home_area=pl.col("area").sort_by("n", descending=True).first(),
            home_n=pl.col("n").max())
        .filter((pl.col("daily_n") >= MIN_HOME_TX) & (pl.col("home_n") / pl.col("daily_n") >= MIN_HOME_SHARE))
        .select("pymt_crd_acct_num_raw", "home_area"))

    resident_cards = home.filter(pl.col("home_area").str.contains(pattern))
    print(f"Karty z pewnym kodem domowym (cały plik): {home.height:,}; "
          f"w wybranych kodach: {resident_cards.height:,}")
    if resident_cards.is_empty():
        print("Brak kart z pewnym kodem domowym w wybranych kodach.")
        return

    # jeden przebieg po transakcjach mieszkańców
    agg = collect(
        dom.join(resident_cards.lazy(), on="pymt_crd_acct_num_raw")
        .group_by("home_area", "area", "mrch_catg_nm", "cp", "is_daily")
        .agg(n=pl.len(), amt=pl.col("amt").sum()))
    local = pl.col("area") == pl.col("home_area")
    cp = agg.filter(pl.col("cp"))

    show("B1_self_sufficiency", cp.filter(pl.col("is_daily")).group_by("home_area").agg(
        n_daily=pl.col("n").sum(), n_daily_local=pl.col("n").filter(local).sum(),
    ).with_columns(self_sufficiency=(pl.col("n_daily_local") / pl.col("n_daily")).round(4)))

    show("B2_outflow_top5", cp.filter(~local).group_by("home_area", "area").agg(
        n=pl.col("n").sum(), amt=pl.col("amt").sum())
         .with_columns(rank=pl.col("n").rank("ordinal", descending=True).over("home_area"))
         .filter(pl.col("rank") <= 5).sort("home_area", "rank"))

    show("B4_outflow_by_category", cp.group_by("home_area", "mrch_catg_nm").agg(
        n=pl.col("n").sum(), n_local=pl.col("n").filter(local).sum())
         .with_columns(n_out=pl.col("n") - pl.col("n_local"),
                       outflow_share=(1 - pl.col("n_local") / pl.col("n")).round(4))
         .with_columns(rank=pl.col("n_out").rank("ordinal", descending=True).over("home_area"))
         .filter(pl.col("rank") <= 10).sort("home_area", "rank"))

    show("B6_ecommerce_share", agg.group_by("home_area").agg(
        n=pl.col("n").sum(), n_cnp=pl.col("n").filter(~pl.col("cp")).sum(),
        n_digital=pl.col("n").filter(pl.col("mrch_catg_nm").str.to_uppercase().str.contains("DIGITAL")).sum(),
    ).with_columns(cnp_share=(pl.col("n_cnp") / pl.col("n")).round(4),
                   digital_share=(pl.col("n_digital") / pl.col("n")).round(4)))

    # napływ (B3) i turysta krajowy (A4): transakcje w wybranym obszarze wg kodu domowego karty
    inflow = (sel_df.filter(~pl.col("is_business") & ~pl.col("is_foreign") & pl.col("cp"))
              .join(home, on="pymt_crd_acct_num_raw"))
    if inflow.height:
        show("B3_inflow_top5", inflow.filter(pl.col("area") != pl.col("home_area"))
             .group_by("area", "home_area").agg(n=pl.len(), amt=pl.col("amt").sum())
             .with_columns(rank=pl.col("n").rank("ordinal", descending=True).over("area"))
             .filter(pl.col("rank") <= 5).sort("area", "rank"))
        show("A4_domestic_guests", inflow.group_by("area").agg(
            n_all=pl.len(), n_guests=(pl.col("area") != pl.col("home_area")).sum(),
        ).with_columns(share_guests=(pl.col("n_guests") / pl.col("n_all")).round(4)))


# ------------------------------------------------------------------ main
def main():
    codes, filter_col, with_b = ask_input()
    pattern = "|".join(re.escape(c) for c in codes)

    data = pl.scan_parquet(SRC)
    base = prepare(data)

    filter_expr = pl.col("area" if filter_col == "mrch_postal_code" else "pstl_cd_enr").str.contains(pattern)
    clean_data = collect(base.filter(filter_expr))

    print(clean_data.shape)
    print(clean_data.head())
    if clean_data.is_empty():
        print("Brak rekordów dla podanych kodów.")
        return

    with pl.Config(tbl_rows=50, tbl_cols=30, tbl_width_chars=200):
        stats_a(clean_data)
        stats_c(clean_data)
        stats_d(clean_data)
        if with_b:
            stats_b(base, clean_data, pattern)
    print(f"\nTabele zapisano w {OUT_DIR}/")


if __name__ == "__main__":
    main()