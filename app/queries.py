import json
from functools import lru_cache
from pathlib import Path

import duckdb
import pandas as pd


DB = "dataset/datasprint_sample_data.parquet"


def _con():
    return duckdb.connect()


def get_miasta() -> pd.DataFrame:
    """Agregat dla wszystkich miast — ładowany raz przy starcie."""
    return _con().execute(f"""
        SELECT
            UPPER(TRIM(mrch_city_nm_raw))                        AS miasto,
            COUNT(*)                                             AS n_transakcji,
            COUNT(DISTINCT pymt_crd_acct_num_raw)                AS n_kart,
            ROUND(AVG(cs_tran_amt), 1)                           AS avg_kwota,
            ROUND(SUM(cs_tran_amt), 0)                           AS suma_kwot,

            -- % turystów (karta spoza Polski)
            ROUND(100.0 * SUM(
                CASE WHEN issr_ctry_nm != 'POLAND' THEN 1 ELSE 0 END
            ) / COUNT(*), 1)                                     AS pct_turystow,

            -- średnia kwota: turysta vs lokalny
            ROUND(AVG(CASE WHEN issr_ctry_nm != 'POLAND'
                THEN cs_tran_amt END), 1)                        AS avg_kwota_turysta,
            ROUND(AVG(CASE WHEN issr_ctry_nm  = 'POLAND'
                THEN cs_tran_amt END), 1)                        AS avg_kwota_lokalny,

            -- kanały płatności (%)
            ROUND(100.0 * SUM(
                CASE WHEN channel_flg = 'mobile' THEN 1 ELSE 0 END
            ) / COUNT(*), 1)                                     AS pct_mobile,
            ROUND(100.0 * SUM(
                CASE WHEN channel_flg = 'cp_contactless' THEN 1 ELSE 0 END
            ) / COUNT(*), 1)                                     AS pct_zblizeniowe,
            ROUND(100.0 * SUM(
                CASE WHEN channel_flg = 'eci' THEN 1 ELSE 0 END
            ) / COUNT(*), 1)                                     AS pct_online

        FROM read_parquet('{DB}')
        GROUP BY UPPER(TRIM(mrch_city_nm_raw))
        HAVING COUNT(DISTINCT pymt_crd_acct_num_raw) >= 30
        ORDER BY n_transakcji DESC
    """).df()


def get_top_kategorie(miasto: str, limit: int = 8) -> pd.DataFrame:
    """Top kategorie sklepów dla danego miasta."""
    return _con().execute(f"""
        SELECT
            mrch_catg_nm                 AS kategoria,
            COUNT(*)                     AS n,
            ROUND(AVG(cs_tran_amt), 1)   AS avg_kwota
        FROM read_parquet('{DB}')
        WHERE UPPER(TRIM(mrch_city_nm_raw)) = '{miasto}'
        GROUP BY kategoria
        ORDER BY n DESC
        LIMIT {limit}
    """).df()


def get_turysci_kraje(miasto: str, limit: int = 8) -> pd.DataFrame:
    """Skąd przyjeżdżają turyści do danego miasta."""
    return _con().execute(f"""
        SELECT
            issr_ctry_nm                 AS kraj,
            COUNT(*)                     AS n_transakcji,
            ROUND(AVG(cs_tran_amt), 1)   AS avg_kwota
        FROM read_parquet('{DB}')
        WHERE UPPER(TRIM(mrch_city_nm_raw)) = '{miasto}'
          AND issr_ctry_nm != 'POLAND'
        GROUP BY kraj
        ORDER BY n_transakcji DESC
        LIMIT {limit}
    """).df()


def get_trendy_miesiac(miasto: str) -> pd.DataFrame:
    """Liczba transakcji per miesiąc — lokalni vs turyści."""
    return _con().execute(f"""
        SELECT
            CAST(prch_mnth_id AS VARCHAR)   AS miesiac,
            COUNT(*)                         AS n_transakcji,
            SUM(CASE WHEN issr_ctry_nm != 'POLAND'
                THEN 1 ELSE 0 END)           AS n_turystow,
            SUM(CASE WHEN issr_ctry_nm  = 'POLAND'
                THEN 1 ELSE 0 END)           AS n_lokalnych
        FROM read_parquet('{DB}')
        WHERE UPPER(TRIM(mrch_city_nm_raw)) = '{miasto}'
        GROUP BY miesiac
        ORDER BY miesiac
    """).df()


def get_stats_postal(kod: str) -> dict:
    """Statystyki transakcji dla danego kodu pocztowego (pstl_cd_enr)."""
    return _con().execute(f"""
        SELECT
            COUNT(*)                                                    AS n_total,
            COUNT(DISTINCT pymt_crd_acct_num_raw)                       AS n_kart_total,
            SUM(CASE WHEN issr_ctry_nm != 'POLAND' THEN 1 ELSE 0 END)  AS n_turysci,
            COUNT(DISTINCT CASE WHEN issr_ctry_nm != 'POLAND'
                THEN pymt_crd_acct_num_raw END)                         AS n_kart_turysci,
            SUM(CASE WHEN issr_ctry_nm  = 'POLAND' THEN 1 ELSE 0 END)  AS n_lokalni
        FROM read_parquet('{DB}')
        WHERE pstl_cd_enr = '{kod}'
    """).df().iloc[0].to_dict()


def get_stats_gmina(postal_codes: list[str]) -> dict:
    """Statystyki transakcji dla listy kodów pocztowych (cała gmina)."""
    codes_str = ", ".join(f"'{c}'" for c in postal_codes)
    return _con().execute(f"""
        SELECT
            COUNT(*)                                                    AS n_total,
            COUNT(DISTINCT pymt_crd_acct_num_raw)                       AS n_kart_total,
            SUM(CASE WHEN issr_ctry_nm != 'POLAND' THEN 1 ELSE 0 END)  AS n_turysci,
            COUNT(DISTINCT CASE WHEN issr_ctry_nm != 'POLAND'
                THEN pymt_crd_acct_num_raw END)                         AS n_kart_turysci,
            SUM(CASE WHEN issr_ctry_nm  = 'POLAND' THEN 1 ELSE 0 END)  AS n_lokalni
        FROM read_parquet('{DB}')
        WHERE pstl_cd_enr IN ({codes_str})
    """).df().iloc[0].to_dict()


def get_kanaly(miasto: str) -> pd.DataFrame:
    """Rozkład kanałów płatności dla danego miasta."""
    return _con().execute(f"""
        SELECT
            channel_flg   AS kanal,
            COUNT(*)      AS n
        FROM read_parquet('{DB}')
        WHERE UPPER(TRIM(mrch_city_nm_raw)) = '{miasto}'
        GROUP BY kanal
        ORDER BY n DESC
    """).df()


# ── Tematy JSON (dataset/json, patrz build_marts.py; format: {"cols": [...], "data": {gmina: [[...]]}}) ──
JSON_DIR = Path("dataset/json")
_TOPICS = ("t_structure", "t_categories", "t_visitors", "t_payments", "t_months", "t_hours", "t_countries", "t_cards", "t_dominant")
NATIONAL = "_PL"  # klucz z sumą dla całego kraju


@lru_cache(maxsize=None)
def _topic(name: str) -> dict:
    with open(JSON_DIR / f"{name}.json", encoding="utf-8") as f:
        return json.load(f)


def _df(topic: str, gmina: str | None) -> pd.DataFrame:
    t = _topic(topic)
    return pd.DataFrame(t["data"].get(gmina or NATIONAL, []), columns=t["cols"])


def marts_ready() -> bool:
    return all((JSON_DIR / f"{t}.json").exists() for t in _TOPICS)


def get_marts_meta() -> dict:
    """Źródło i pokrycie danych (do pokazania użytkownikowi)."""
    path = JSON_DIR / "_meta.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def get_gmina_group_table() -> pd.DataFrame:
    """Wszystkie gminy x grupa kategorii (wejście do app.trade): transakcje, kwota, transakcje kartami zagranicznymi."""
    t = _topic("t_structure")
    rows = [(g, *r) for g, rs in t["data"].items() if g != NATIONAL for r in rs]
    df = pd.DataFrame(rows, columns=["gmina", *t["cols"]])
    df["guest_tx"] = df["n"].where(df["visitor"] == "zagr", 0)
    return df.groupby(["gmina", "grupa"], as_index=False).agg(n_tx=("n", "sum"), amt=("amt", "sum"), guest_tx=("guest_tx", "sum"))


def get_structure(gmina: str) -> pd.DataFrame:
    """Grupa kategorii x typ kupującego: transakcje i kwota."""
    return _df("t_structure", gmina).rename(columns={"n": "n_tx"})


def get_categories(gmina: str, limit: int = 15) -> pd.DataFrame:
    """Najczęstsze kategorie sprzedawców w gminie z podziałem na typ kupującego."""
    return _df("t_categories", gmina).rename(
        columns={"cat": "kategoria", "n": "n_tx", "avg_amt": "sr_rachunek"}).head(limit)


def get_visitors(gmina: str | None) -> pd.DataFrame:
    return _df("t_visitors", gmina).rename(columns={"n": "n_tx"})


def get_payments(gmina: str | None) -> pd.DataFrame:
    return _df("t_payments", gmina).rename(columns={"n": "n_tx"})


def get_months(gmina: str) -> pd.DataFrame:
    return _df("t_months", gmina).rename(columns={"n": "n_tx"})


def get_hours(gmina: str) -> pd.DataFrame:
    """Godzina (czas PL) x dzień tygodnia (0 = niedziela); hr = -1 oznacza brak czasu w danych."""
    return _df("t_hours", gmina).rename(columns={"n": "n_tx"})


def get_countries(gmina: str, limit: int = 10) -> pd.DataFrame:
    return _df("t_countries", gmina).rename(
        columns={"country": "kraj", "n": "n_tx", "avg_amt": "sr_rachunek"}).head(limit)


def get_countries_total(gmina: str) -> int:
    return int(_topic("t_countries").get("extra", {}).get("foreign_total", {}).get(gmina, 0))


def get_card_types(gmina: str | None) -> pd.DataFrame:
    return _df("t_cards", gmina).rename(columns={"n": "n_tx"})


def get_dominant_categories() -> dict[str, dict]:
    """Dominująca grupa kategorii per gmina — {gmina: {grupa, n, pct, avg_amt}}."""
    t = _topic("t_dominant")
    out = {}
    for gmina, rows in t["data"].items():
        if rows:
            cols = t["cols"]
            out[gmina] = dict(zip(cols, rows[0]))
    return out
