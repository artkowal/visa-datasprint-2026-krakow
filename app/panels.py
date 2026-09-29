"""Panele Streamlit dla wybranej gminy: kto kupuje, jak płaci, co kupuje, kiedy i skąd są goście.

Wszystkie liczby pochodzą z tabel zagregowanych (build_marts.py). Wartości bezwzględne dotyczą próbki
(20% kart); udziały nie zależą od skali. Kwoty są w walucie fikcyjnej (tylko porównania względne).
"""
import altair as alt
import pandas as pd
import streamlit as st

from . import queries as Q
from .categories import EXCLUDED_FROM_LOCAL, labeled
from .trade import GAP_LQ, MIN_TX, SPEC_LQ, profile

SAMPLE_SCALE = 4.96  # full / sample dla kart (test próbki: 15 218 416 / 3 066 582 transakcji)

VISITORS = {
    "mieszk": {"icon": "🏠", "label": "Mieszkańcy gminy", "color": "#8b5cf6"},
    "pl_gosc": {"icon": "🚗", "label": "Goście z Polski", "color": "#0ea5e9"},
    "zagr": {"icon": "✈️", "label": "Goście z zagranicy", "color": "#f97316"},
    "nieznany": {"icon": "❔", "label": "Bez danych o pochodzeniu", "color": "#94a3b8"},
}
VIS_ORDER = list(VISITORS)
VIS_LABELS = [v["label"] for v in VISITORS.values()]
VIS_COLORS = [v["color"] for v in VISITORS.values()]
VIS_SCALE = alt.Scale(domain=VIS_LABELS, range=VIS_COLORS)

PAYMENTS = {  # (channel_flg, cp_flag) -> (ikona, etykieta)
    "cp_contactless": ("📶", "Zbliżeniowo (karta lub telefon)"),
    "cp_non_contactless": ("💳", "Karta włożona lub przeciągnięta"),
    "mobile_1": ("📱", "Portfel mobilny w sklepie"),
    "mobile_0": ("📲", "Aplikacja mobilna (online)"),
    "eci": ("🛒", "Zakupy w internecie"),
    "recur": ("🔁", "Płatności cykliczne"),
    "moto": ("☎️", "Telefon lub poczta"),
    "other": ("❔", "Inne"),
}
DOW_LABELS = {1: "Pn", 2: "Wt", 3: "Śr", 4: "Cz", 5: "Pt", 6: "Sb", 0: "Nd"}
DOW_ORDER = ["Pn", "Wt", "Śr", "Cz", "Pt", "Sb", "Nd"]


# ── pomocnicze ────────────────────────────────────────────────────────────────
def num(x: float) -> str:
    return f"{int(round(x)):,}".replace(",", " ")


def pct(x: float, digits: int = 0) -> str:
    return "–" if pd.isna(x) else f"{100 * x:.{digits}f}%"


def _vis_label(code: str) -> str:
    return VISITORS[code]["label"]


def _pay_key(ch: str, cp: int) -> str:
    return f"mobile_{1 if cp == 1 else 0}" if ch == "mobile" else (ch if ch in PAYMENTS else "other")


def _month_label(m: int) -> str:
    return f"{m // 100}-{m % 100:02d}"


@st.cache_data(show_spinner=False)
def _visitors(g): return Q.get_visitors(g)
@st.cache_data(show_spinner=False)
def _payments(g): return Q.get_payments(g)
@st.cache_data(show_spinner=False)
def _structure(g): return Q.get_structure(g)
@st.cache_data(show_spinner=False)
def _categories(g): return Q.get_categories(g, 15)
@st.cache_data(show_spinner=False)
def _months(g): return Q.get_months(g)
@st.cache_data(show_spinner=False)
def _hours(g): return Q.get_hours(g)
@st.cache_data(show_spinner=False)
def _countries(g): return Q.get_countries(g, 10)
@st.cache_data(show_spinner=False)
def _cards(g): return Q.get_card_types(g)


def _stacked_visitor_bar(df: pd.DataFrame, y: str, value: str, y_sort=None, height: int = 300, normalize: bool = False):
    """Słupki poziome dzielone na typ kupującego."""
    d = df.copy()
    d["Kupujący"] = d["visitor"].map(_vis_label)
    d["_rank"] = d["visitor"].map({v: i for i, v in enumerate(VIS_ORDER)})
    x = alt.X(f"{value}:Q", stack="normalize" if normalize else True,
              axis=alt.Axis(format="%" if normalize else "~s", title=None))
    return alt.Chart(d).mark_bar().encode(
        y=alt.Y(f"{y}:N", sort=y_sort, title=None), x=x,
        color=alt.Color("Kupujący:N", scale=VIS_SCALE, legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("_rank:Q"),
        tooltip=[y, "Kupujący", alt.Tooltip(f"{value}:Q", format=",.0f", title="Transakcje")],
    ).properties(height=height)


# ── sekcje ────────────────────────────────────────────────────────────────────
def _section_header(g: str, vis: pd.DataFrame, nat_vis: pd.DataFrame, meta: dict) -> None:
    total = vis["n_tx"].sum()
    ticket = vis["amt"].sum() / total
    nat_ticket = nat_vis["amt"].sum() / nat_vis["n_tx"].sum()
    scaled = meta.get("source_kind") == "sample"
    c1, c2, c3 = st.columns(3)
    c1.metric("🧾 Transakcje w próbce", num(total))
    c2.metric("📈 Szacunek dla wszystkich kart" if scaled else "📈 Transakcje", f"≈ {num(total * SAMPLE_SCALE)}" if scaled else num(total),
              help="Próbka to losowe 20% kart z pełną historią; mnożnik ≈ 4,96 wynika z porównania z pełnym zbiorem.")
    c3.metric("💰 Średni rachunek vs średnia w Polsce", f"×{ticket / nat_ticket:.2f}",
              help="Kwoty są w walucie fikcyjnej, dlatego pokazujemy tylko porównanie względne.")


def _section_visitors(g: str, vis: pd.DataFrame, nat_vis: pd.DataFrame, meta: dict) -> None:
    st.markdown("### 👥 Kto tu kupuje?")
    v = vis.set_index("visitor").reindex(VIS_ORDER).fillna(0)
    nv = nat_vis.set_index("visitor").reindex(VIS_ORDER).fillna(0)
    total, nat_total = v["n_tx"].sum(), nv["n_tx"].sum()
    gm_ticket = v["amt"].sum() / total
    cols = st.columns(len(VIS_ORDER))
    for col, code in zip(cols, VIS_ORDER):
        share, nat_share = v.loc[code, "n_tx"] / total, nv.loc[code, "n_tx"] / nat_total
        info = VISITORS[code]
        with col:
            st.metric(f"{info['icon']} {info['label']}", pct(share, 1), f"Polska: {pct(nat_share, 1)}", delta_color="off")
            rel = (v.loc[code, "amt"] / v.loc[code, "n_tx"]) / gm_ticket if v.loc[code, "n_tx"] else float("nan")
            st.caption(f"{num(v.loc[code, 'n_tx'])} transakcji · rachunek ×{rel:.2f}" if v.loc[code, "n_tx"] else "brak transakcji")

    bars = pd.concat([
        v.reset_index().assign(metryka="Liczba transakcji", val=lambda d: d["n_tx"]),
        v.reset_index().assign(metryka="Wartość zakupów", val=lambda d: d["amt"]),
    ])
    st.altair_chart(_stacked_visitor_bar(bars, "metryka", "val", y_sort=["Liczba transakcji", "Wartość zakupów"],
                                         height=110, normalize=True), use_container_width=True)

    known_pl = v.loc["mieszk", "n_tx"] + v.loc["pl_gosc", "n_tx"]
    if known_pl >= 100:
        st.info(f"Wśród kupujących kartami polskimi o znanym pochodzeniu **{pct(v.loc['mieszk', 'n_tx'] / known_pl)}** "
                f"to mieszkańcy gminy, a **{pct(v.loc['pl_gosc', 'n_tx'] / known_pl)}** – przyjezdni z innych gmin.", icon="🏠")
    unknown = v.loc["nieznany", "n_tx"] / total
    if unknown > 0.10:
        months = ", ".join(_month_label(m) for m in meta.get("origin_missing_months", []))
        st.caption(f"❔ Dla {pct(unknown)} transakcji karta polska nie ma przypisanego miejsca stałego przebywania "
                   f"(dostawca danych nie podaje go m.in. w: {months or 'części miesięcy'}). Udziały powyżej liczone są na wszystkich transakcjach.")


def _section_payments(g: str, pay: pd.DataFrame, nat_pay: pd.DataFrame) -> None:
    st.markdown("### 💳 Jak płacą?")
    def place_share(df):
        on_site = df.loc[df["cp"] == 1, "n_tx"].sum()
        return on_site / df["n_tx"].sum()

    on_site, nat_on_site = place_share(pay), place_share(nat_pay)
    total = pay["n_tx"].sum()
    c1, c2 = st.columns(2)
    c1.metric("🏪 Na miejscu (karta fizycznie obecna)", pct(on_site, 1), f"Polska: {pct(nat_on_site, 1)}", delta_color="off")
    c1.caption(f"{num(pay.loc[pay['cp'] == 1, 'n_tx'].sum())} transakcji")
    c2.metric("🌐 Online lub zdalnie (karta nieobecna)", pct(1 - on_site, 1), f"Polska: {pct(1 - nat_on_site, 1)}", delta_color="off")
    c2.caption(f"{num(pay.loc[pay['cp'] != 1, 'n_tx'].sum())} transakcji")

    by_method = pay.assign(key=[_pay_key(c, p) for c, p in zip(pay["ch"], pay["cp"])]).groupby("key", as_index=False)["n_tx"].sum()
    by_method["Sposób płatności"] = by_method["key"].map(lambda k: f"{PAYMENTS[k][0]} {PAYMENTS[k][1]}")
    by_method["udzial"] = by_method["n_tx"] / total
    by_method["etykieta"] = [f"{pct(u, 1)} · {num(n)}" for u, n in zip(by_method["udzial"], by_method["n_tx"])]
    order = by_method.sort_values("n_tx", ascending=False)["Sposób płatności"].tolist()
    base = alt.Chart(by_method).encode(y=alt.Y("Sposób płatności:N", sort=order, title=None),
                                       x=alt.X("udzial:Q", axis=alt.Axis(format="%", title=None)))
    st.altair_chart(base.mark_bar(color="#6366f1") + base.mark_text(align="left", dx=4).encode(text="etykieta:N"),
                    use_container_width=True)

    online_by_visitor = pay.assign(online=(pay["cp"] != 1)).groupby(["visitor", "online"], as_index=False)["n_tx"].sum()
    rows = []
    for code in ["mieszk", "pl_gosc", "zagr"]:
        d = online_by_visitor[online_by_visitor["visitor"] == code]
        if d["n_tx"].sum() >= 100:
            rows.append({"Kupujący": _vis_label(code), "udzial": d.loc[d["online"], "n_tx"].sum() / d["n_tx"].sum(),
                         "n": d["n_tx"].sum()})
    if rows:
        d = pd.DataFrame(rows)
        d["etykieta"] = d["udzial"].map(lambda x: pct(x, 1))
        base = alt.Chart(d).encode(y=alt.Y("Kupujący:N", sort=None, title=None),
                                   x=alt.X("udzial:Q", axis=alt.Axis(format="%", title="Udział płatności online lub zdalnych")))
        st.altair_chart((base.mark_bar().encode(color=alt.Color("Kupujący:N", scale=VIS_SCALE, legend=None))
                         + base.mark_text(align="left", dx=4).encode(text="etykieta:N")).properties(height=110),
                        use_container_width=True)


def _section_products(g: str, struct: pd.DataFrame, prof: dict) -> None:
    st.markdown("### 🛍️ Co kupują i kto?")
    if prof["status"] != "ok":
        st.warning(f"Za mało danych do oceny struktury handlu ({prof.get('n_local', 0):,} transakcji lokalnych, próg {MIN_TX:,}).")
        return
    t = prof["table"]
    top = t.iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("🏆 Dominująca grupa", top["grupa"], f"{pct(top['udzial'])} transakcji", delta_color="off")
    c2.metric("🎨 Różnorodność oferty (0–1)", f"{prof['diversity']:.2f}",
              f"większa niż w {prof['diversity_pct_peers']:.0f}% podobnych gmin", delta_color="off",
              help="Znormalizowana entropia udziałów grup kategorii: 0 = wszystko w jednej grupie, 1 = równy rozkład.")
    c3.metric("🌐 Zakupy internetowe pominięte", pct(prof["online_share"], 1),
              help="Sprzedawcy internetowi są przypisani do siedziby firmy, nie do miejsca zakupu, więc nie liczą się do lokalnego handlu.")
    if prof["low_confidence"]:
        st.warning("Mała próba – wskaźniki obarczone dużym błędem.")

    local = struct[~struct["grupa"].isin(EXCLUDED_FROM_LOCAL)].copy()
    totals = local.groupby("grupa")["n_tx"].sum().sort_values(ascending=False)
    keep = totals.head(10).index.tolist()
    local = local[local["grupa"].isin(keep)]
    local["Grupa"] = local["grupa"].map(labeled)
    order = [labeled(x) for x in keep]
    st.caption("Grupy kategorii według liczby transakcji; kolor pokazuje, kto kupował.")
    st.altair_chart(_stacked_visitor_bar(local, "Grupa", "n_tx", y_sort=order, height=340), use_container_width=True)

    spec, gaps = t[t["ocena"] == "specjalizacja"], t[t["ocena"] == "luka"]
    st.markdown("**Mocne strony** (udział ≥ {:.1f}× większy niż w podobnych gminach)".format(SPEC_LQ))
    if spec.empty:
        st.caption("Brak wyraźnych specjalizacji.")
    else:
        st.markdown(" ".join(f":green-badge[{labeled(r.grupa)} ×{r.lq_rowiesnicy:.1f}]" for r in spec.itertuples()))
    st.markdown("**Luki** (udział ≤ {:.1f}× względem podobnych gmin)".format(GAP_LQ))
    if gaps.empty:
        st.caption("Brak wyraźnych luk.")
    else:
        st.markdown(" ".join(f":orange-badge[{labeled(r.grupa)} ×{r.lq_rowiesnicy:.1f}]" for r in gaps.itertuples()))
    st.caption(f"Porównanie z {prof['n_peers']} gminami najbliższymi wielkością "
               f"({num(prof['peer_size_range'][0])}–{num(prof['peer_size_range'][1])} transakcji lokalnych).")


def _section_time(g: str, months: pd.DataFrame, hours: pd.DataFrame, meta: dict) -> None:
    st.markdown("### 🕒 Kiedy kupują?")
    m = months.copy()
    m["Miesiąc"] = m["mon"].map(_month_label)
    m["Kupujący"] = m["visitor"].map(_vis_label)
    m["_rank"] = m["visitor"].map({v: i for i, v in enumerate(VIS_ORDER)})
    st.caption("Liczba transakcji w miesiącu")
    st.altair_chart(alt.Chart(m).mark_bar().encode(
        x=alt.X("Miesiąc:O", title=None), y=alt.Y("n_tx:Q", title=None, axis=alt.Axis(format="~s")),
        color=alt.Color("Kupujący:N", scale=VIS_SCALE, legend=alt.Legend(orient="bottom", title=None)),
        order=alt.Order("_rank:Q"),
        tooltip=["Miesiąc", "Kupujący", alt.Tooltip("n_tx:Q", format=",.0f", title="Transakcje")],
    ).properties(height=230), use_container_width=True)

    choice = st.radio("Rytm dnia dla:", ["Wszyscy", *[_vis_label(v) for v in ["mieszk", "pl_gosc", "zagr"]]],
                      horizontal=True, key=f"rytm_{g}")
    h = hours.copy()
    if choice != "Wszyscy":
        h = h[h["visitor"].map(_vis_label) == choice]
    missing = h.loc[h["hr"] < 0, "n_tx"].sum() / h["n_tx"].sum() if h["n_tx"].sum() else 0
    h = h[h["hr"] >= 0].groupby(["dow", "hr"], as_index=False)["n_tx"].sum()
    if h["n_tx"].sum() < 200:
        st.caption("Za mało transakcji z godziną, żeby pokazać rytm dnia.")
        return
    h["Dzień"] = h["dow"].map(DOW_LABELS)
    h["udzial"] = h["n_tx"] / h["n_tx"].sum()
    st.caption("Kiedy w tygodniu płacą (godzina w czasie polskim; ciemniejszy = więcej transakcji)")
    st.altair_chart(alt.Chart(h).mark_rect().encode(
        x=alt.X("hr:O", title="Godzina"), y=alt.Y("Dzień:N", sort=DOW_ORDER, title=None),
        color=alt.Color("udzial:Q", scale=alt.Scale(scheme="purples"), legend=alt.Legend(format="%", title="Udział")),
        tooltip=["Dzień", alt.Tooltip("hr:O", title="Godzina"), alt.Tooltip("udzial:Q", format=".2%", title="Udział"),
                 alt.Tooltip("n_tx:Q", format=",.0f", title="Transakcje")],
    ).properties(height=220), use_container_width=True)
    if missing > 0.02:
        st.caption(f"Pominięto {pct(missing)} transakcji bez godziny w danych (zapis 000000).")


def _section_guests(g: str, countries: pd.DataFrame, cards: pd.DataFrame, nat_cards: pd.DataFrame) -> None:
    st.markdown("### 🌍 Skąd są goście i jakimi kartami płacą?")
    total_foreign = Q.get_countries_total(g)
    left, right = st.columns([3, 2])
    with left:
        if total_foreign < 100:
            st.caption("Za mało transakcji kartami zagranicznymi, żeby pokazać kraje.")
        else:
            d = countries.copy()
            d["udzial"] = d["n_tx"] / total_foreign
            d["etykieta"] = [f"{pct(u, 1)} · {num(n)}" for u, n in zip(d["udzial"], d["n_tx"])]
            st.caption(f"Kraje wydania karty – {num(total_foreign)} transakcji kartami zagranicznymi")
            base = alt.Chart(d).encode(y=alt.Y("kraj:N", sort=list(d["kraj"]), title=None),
                                       x=alt.X("udzial:Q", axis=alt.Axis(format="%", title=None)),
                                       tooltip=["kraj", alt.Tooltip("n_tx:Q", format=",.0f", title="Transakcje"),
                                                alt.Tooltip("sr_rachunek:Q", format=",.0f", title="Śr. rachunek (fikcyjna waluta)")])
            st.altair_chart(base.mark_bar(color=VISITORS["zagr"]["color"]) + base.mark_text(align="left", dx=4).encode(text="etykieta:N"),
                            use_container_width=True)
    with right:
        st.caption("Udział kart premium (Infinite, Platinum, Premier, Signature)")
        def prem_share(df, code):
            d = df[df["visitor"] == code]
            return d.loc[d["prem"], "n_tx"].sum() / d["n_tx"].sum() if d["n_tx"].sum() >= 100 else float("nan")
        for code in ["mieszk", "pl_gosc", "zagr"]:
            info = VISITORS[code]
            st.metric(f"{info['icon']} {info['label']}", pct(prem_share(cards, code), 1),
                      f"Polska: {pct(prem_share(nat_cards, code), 1)}", delta_color="off")


def _section_details(g: str, struct: pd.DataFrame, cats: pd.DataFrame, pay: pd.DataFrame, prof: dict, meta: dict) -> None:
    with st.expander("📋 Szczegóły i dane źródłowe"):
        tab_c, tab_g, tab_p, tab_q = st.tabs(["Kategorie", "Grupy vs podobne gminy", "Płatności", "Jakość danych"])
        with tab_c:
            d = cats.copy()
            for col in ["mieszk", "pl_gosc", "zagr", "nieznany"]:
                d[col] = d[col].fillna(0)
            st.dataframe(d, hide_index=True, use_container_width=True, column_config={
                "kategoria": "Kategoria", "grupa": "Grupa", "n_tx": "Transakcje",
                "sr_rachunek": st.column_config.NumberColumn("Śr. rachunek", format="%.0f"),
                "mieszk": "🏠 Mieszkańcy", "pl_gosc": "🚗 Goście PL", "zagr": "✈️ Zagranica", "nieznany": "❔ Bez danych"})
        with tab_g:
            if prof["status"] == "ok":
                t = prof["table"]
                show = t.assign(udzial=t["udzial"] * 100, udzial_rowiesnicy=t["udzial_rowiesnicy"] * 100,
                                udzial_polska=t["udzial_polska"] * 100, udzial_gosci=t["udzial_gosci"] * 100)[
                    ["grupa", "n_tx", "udzial", "udzial_rowiesnicy", "udzial_polska", "lq_rowiesnicy", "sr_rachunek", "udzial_gosci", "ocena"]]
                st.dataframe(show, hide_index=True, use_container_width=True, column_config={
                    "grupa": "Grupa", "n_tx": "Transakcje",
                    "udzial": st.column_config.NumberColumn("Udział [%]", format="%.1f"),
                    "udzial_rowiesnicy": st.column_config.NumberColumn("Podobne gminy [%]", format="%.1f"),
                    "udzial_polska": st.column_config.NumberColumn("Polska [%]", format="%.1f"),
                    "lq_rowiesnicy": st.column_config.NumberColumn("× podobne gminy", format="%.2f"),
                    "sr_rachunek": st.column_config.NumberColumn("Śr. rachunek", format="%.0f"),
                    "udzial_gosci": st.column_config.NumberColumn("Zagraniczni [%]", format="%.1f"), "ocena": "Ocena"})
            else:
                st.caption("Za mało danych.")
        with tab_p:
            d = pay.assign(key=[_pay_key(c, p) for c, p in zip(pay["ch"], pay["cp"])])
            piv = d.pivot_table(index="key", columns="visitor", values="n_tx", aggfunc="sum", fill_value=0)
            piv = piv.reindex(columns=VIS_ORDER, fill_value=0)
            piv.insert(0, "Sposób płatności", [f"{PAYMENTS[k][0]} {PAYMENTS[k][1]}" for k in piv.index])
            piv["Razem"] = piv[VIS_ORDER].sum(axis=1)
            st.dataframe(piv.sort_values("Razem", ascending=False).rename(columns={k: _vis_label(k) for k in VIS_ORDER}),
                         hide_index=True, use_container_width=True)
        with tab_q:
            st.markdown(
                f"- **Źródło:** {meta.get('source_kind', '?')} (`{meta.get('source', '?')}`), zbudowano {meta.get('built_at', '?')}\n"
                f"- **Zakres:** {meta.get('filters', '')}\n"
                f"- **Pokrycie:** {meta.get('pct_with_postal', '?')}% transakcji ma kod pocztowy, "
                f"{meta.get('pct_mapped_to_gmina', '?')}% da się przypisać do gminy\n"
                "- **Próbka:** losowe 20% kart z pełną historią – udziały są wiarygodne, wartości bezwzględne trzeba skalować (×≈4,96)\n"
                "- **Kwoty:** waluta fikcyjna (hackathon), używamy tylko porównań względnych\n"
                "- **Kupujący:** *mieszkaniec* = karta polska, której szacowane miejsce stałego przebywania (`lau_enr`) to ta gmina; "
                "*gość z Polski* = karta polska z innej gminy; *gość z zagranicy* = karta wydana poza Polską. "
                "Miejsce stałego przebywania to szacunek dostawcy danych i bywa zmienne; przy granicy gmin możliwe pomyłki\n"
                "- **Kod pocztowy → gmina:** gmina o największej powierzchni kodu; część kodów leży w kilku gminach\n"
                "- **Czas:** godzina w czasie polskim wyliczona z GMT; transakcje z zapisem 000000 pomijane w rytmie dnia\n"
                "- **Płatności:** *na miejscu* = karta fizycznie obecna (`cp_flag=1`), *online/zdalnie* = `cp_flag=0`; "
                "kanał `mobile` obejmuje płatności w sklepie i w aplikacji")


# ── punkt wejścia ─────────────────────────────────────────────────────────────
def render_gmina(g: str, trade_ref, meta: dict) -> None:
    vis = _visitors(g)
    if vis.empty:
        st.info("Brak danych handlowych: żaden kod pocztowy tej gminy nie ma transakcji w tabelach.")
        return
    nat_vis, nat_pay, nat_cards = _visitors(None), _payments(None), _cards(None)
    if vis["n_tx"].sum() < MIN_TX:
        st.warning(f"Za mało danych ({num(vis['n_tx'].sum())} transakcji, próg {num(MIN_TX)}) – wskaźniki byłyby przypadkowe.")
        return
    prof = profile(trade_ref, g)
    _section_header(g, vis, nat_vis, meta)
    st.divider()
    _section_visitors(g, vis, nat_vis, meta)
    st.divider()
    _section_payments(g, _payments(g), nat_pay)
    st.divider()
    _section_products(g, _structure(g), prof)
    st.divider()
    _section_time(g, _months(g), _hours(g), meta)
    st.divider()
    _section_guests(g, _countries(g), _cards(g), nat_cards)
    st.divider()
    _section_details(g, _structure(g), _categories(g), _payments(g), prof, meta)
