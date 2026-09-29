"""Ocena handlu w gminie: struktura kategorii, specjalizacje, luki i porównanie z gminami podobnej wielkości.

Wejście: tabela `get_gmina_group_table()` (gmina, grupa, n_tx, amt, guest_tx).
Wszystkie wskaźniki liczone są na transakcjach lokalnych (bez grup z EXCLUDED_FROM_LOCAL),
bo sprzedawcy internetowi są przypisani do siedziby firmy, a nie do miejsca zakupu.
"""
from dataclasses import dataclass

import numpy as np
import pandas as pd

from .categories import EXCLUDED_FROM_LOCAL, ONLINE

MIN_TX = 1000            # poniżej: "za mało danych"
LOW_CONFIDENCE_TX = 5000  # poniżej: ostrzeżenie o małej próbie
N_PEERS = 50             # tylu najbliższych wielkością gmin tworzy grupę porównawczą
SPEC_LQ = 1.5            # specjalizacja: udział >= 1,5x mediany rówieśników
GAP_LQ = 0.5             # luka: udział <= 0,5x mediany rówieśników
MIN_SHARE = 0.02         # grupa ma znaczenie, gdy rówieśnicy mają w niej >= 2% transakcji
MIN_GROUP_TX = 50        # minimalna liczba transakcji w grupie, by ogłosić specjalizację


@dataclass
class Reference:
    """Zestawienie wszystkich gmin policzone raz."""
    n_all: pd.Series          # transakcje ogółem per gmina
    n_local: pd.Series        # transakcje lokalne per gmina
    tx: pd.DataFrame          # gmina x grupa: transakcje (grupy lokalne)
    amt: pd.DataFrame         # gmina x grupa: kwota
    guest: pd.DataFrame       # gmina x grupa: transakcje kartami zagranicznymi
    shares: pd.DataFrame      # gmina x grupa: udział w transakcjach lokalnych
    national_shares: pd.Series
    national_ticket: float
    diversity: pd.Series      # różnorodność per gmina (tylko gminy >= MIN_TX)
    groups: list[str]


def _diversity(shares: pd.DataFrame) -> pd.Series:
    """Znormalizowana entropia Shannona (0 = jedna grupa, 1 = równy rozkład)."""
    k = shares.shape[1]
    p = shares.to_numpy()
    with np.errstate(divide="ignore", invalid="ignore"):
        h = -np.nansum(np.where(p > 0, p * np.log(p), 0.0), axis=1)
    return pd.Series(h / np.log(k), index=shares.index)


def build_reference(tbl: pd.DataFrame) -> Reference:
    n_all = tbl.groupby("gmina")["n_tx"].sum()
    loc = tbl[~tbl["grupa"].isin(EXCLUDED_FROM_LOCAL)]
    groups = sorted(loc["grupa"].unique())
    tx = loc.pivot_table(index="gmina", columns="grupa", values="n_tx", aggfunc="sum", fill_value=0).reindex(columns=groups, fill_value=0)
    amt = loc.pivot_table(index="gmina", columns="grupa", values="amt", aggfunc="sum", fill_value=0).reindex(columns=groups, fill_value=0)
    guest = loc.pivot_table(index="gmina", columns="grupa", values="guest_tx", aggfunc="sum", fill_value=0).reindex(columns=groups, fill_value=0)
    n_local = tx.sum(axis=1)
    shares = tx.div(n_local.replace(0, np.nan), axis=0)
    nat = tx.sum(axis=0) / tx.to_numpy().sum()
    ticket = float(amt.to_numpy().sum() / tx.to_numpy().sum())
    ok = n_local >= MIN_TX
    diversity = _diversity(shares[ok].fillna(0))
    return Reference(n_all.reindex(tx.index), n_local, tx, amt, guest, shares, nat, ticket, diversity, groups)


def peers_for(ref: Reference, gmina: str, n: int = N_PEERS) -> list[str]:
    """Gminy najbliższe wielkością (log liczby transakcji lokalnych), spośród gmin powyżej progu."""
    eligible = ref.n_local[(ref.n_local >= MIN_TX) & (ref.n_local.index != gmina)]
    dist = (np.log(eligible) - np.log(ref.n_local[gmina])).abs()
    return dist.nsmallest(n).index.tolist()


def profile(ref: Reference, gmina: str) -> dict:
    """Profil handlu gminy. Zwraca status 'brak', 'za_malo_danych' lub 'ok'."""
    if gmina not in ref.n_local.index:
        return {"status": "brak"}
    n_local = int(ref.n_local[gmina])
    n_all = int(ref.n_all[gmina])
    base = {"n_local": n_local, "n_all": n_all, "online_share": 1 - n_local / n_all if n_all else np.nan}
    if n_local < MIN_TX:
        return {"status": "za_malo_danych", **base}

    peers = peers_for(ref, gmina)
    peer_shares = ref.shares.loc[peers]
    peer_median = peer_shares.median()
    own = ref.shares.loc[gmina]

    ticket = float(ref.amt.loc[gmina].sum() / n_local)
    div = float(ref.diversity[gmina])
    peer_div = ref.diversity.reindex(peers)
    div_pct = float((peer_div < div).mean() * 100)

    rows = []
    for g in ref.groups:
        n_g = int(ref.tx.loc[gmina, g])
        lq_peer = own[g] / peer_median[g] if peer_median[g] > 0 else np.nan
        flag = ""
        expected_tx = peer_median[g] * n_local  # ile transakcji miałaby gmina przy udziale rówieśników
        if peer_median[g] >= MIN_SHARE and lq_peer <= GAP_LQ and expected_tx >= MIN_GROUP_TX:
            flag = "luka"
        elif lq_peer >= SPEC_LQ and own[g] >= MIN_SHARE and n_g >= MIN_GROUP_TX:
            flag = "specjalizacja"
        rows.append({
            "grupa": g,
            "n_tx": n_g,
            "udzial": own[g],
            "udzial_polska": ref.national_shares[g],
            "udzial_rowiesnicy": peer_median[g],
            "lq_rowiesnicy": lq_peer,
            "lq_polska": own[g] / ref.national_shares[g] if ref.national_shares[g] > 0 else np.nan,
            "sr_rachunek": float(ref.amt.loc[gmina, g] / n_g) if n_g else np.nan,
            "udzial_gosci": float(ref.guest.loc[gmina, g] / n_g) if n_g else np.nan,
            "ocena": flag,
        })
    table = pd.DataFrame(rows).sort_values("udzial", ascending=False).reset_index(drop=True)

    return {
        "status": "ok",
        **base,
        "low_confidence": n_local < LOW_CONFIDENCE_TX,
        "avg_ticket": ticket,
        "ticket_vs_poland": ticket / ref.national_ticket,
        "diversity": div,
        "diversity_pct_peers": div_pct,
        "n_peers": len(peers),
        "peer_size_range": (int(ref.n_local[peers].min()), int(ref.n_local[peers].max())),
        "table": table,
    }
