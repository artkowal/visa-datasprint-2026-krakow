import io
import base64
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

BG = "#1e1e2e"
FG = "#cdd6f4"
PURPLE = "#a78bfa"
GREEN = "#10b981"
ORANGE = "#f97316"


def _to_base64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight",
                dpi=90, facecolor=BG)
    buf.seek(0)
    encoded = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return encoded


def chart_top_kategorie(df: pd.DataFrame) -> str:
    """Poziomy bar chart — top kategorie sklepów."""
    df = df.copy()
    df["kategoria"] = df["kategoria"].str[:22]
    df = df.sort_values("n")

    fig, ax = plt.subplots(figsize=(4, 2.8))
    bars = ax.barh(df["kategoria"], df["n"], color=PURPLE)
    ax.bar_label(bars, fmt="%d", color=FG, fontsize=7, padding=3)
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, labelsize=7)
    ax.set_title("Top kategorie sklepów", color=FG, fontsize=9, pad=6)
    ax.spines[:].set_visible(False)
    fig.patch.set_facecolor(BG)
    fig.tight_layout()
    return _to_base64(fig)


def chart_turysci_kraje(df: pd.DataFrame) -> str:
    """Poziomy bar chart — skąd turyści."""
    df = df.sort_values("n_transakcji")

    fig, ax = plt.subplots(figsize=(4, 2.8))
    bars = ax.barh(df["kraj"], df["n_transakcji"], color=GREEN)
    ax.bar_label(bars, fmt="%d", color=FG, fontsize=7, padding=3)
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, labelsize=7)
    ax.set_title("Skąd przyjeżdżają turyści", color=FG, fontsize=9, pad=6)
    ax.spines[:].set_visible(False)
    fig.patch.set_facecolor(BG)
    fig.tight_layout()
    return _to_base64(fig)


def chart_trendy(df: pd.DataFrame) -> str:
    """Liniowy wykres — lokalni vs turyści w czasie."""
    fig, ax = plt.subplots(figsize=(5, 2.5))
    ax.plot(df["miesiac"], df["n_lokalnych"],
            color=PURPLE, marker="o", markersize=3, label="Lokalni")
    ax.plot(df["miesiac"], df["n_turystow"],
            color=GREEN, marker="o", markersize=3, label="Turyści")
    ax.set_facecolor(BG)
    ax.tick_params(colors=FG, labelsize=6)
    ax.set_title("Trend miesięczny", color=FG, fontsize=9, pad=6)
    ax.legend(fontsize=7, facecolor=BG, labelcolor=FG)
    ax.spines[:].set_visible(False)
    plt.xticks(rotation=45)
    fig.patch.set_facecolor(BG)
    fig.tight_layout()
    return _to_base64(fig)


def chart_kanaly(df: pd.DataFrame) -> str:
    """Kołowy wykres — kanały płatności."""
    fig, ax = plt.subplots(figsize=(3, 3))
    colors = [PURPLE, GREEN, ORANGE, "#3b82f6", "#ec4899", "#facc15", "#94a3b8"]
    wedges, texts, autotexts = ax.pie(
        df["n"],
        labels=df["kanal"],
        autopct="%1.0f%%",
        colors=colors[:len(df)],
        textprops={"color": FG, "fontsize": 7},
    )
    for at in autotexts:
        at.set_fontsize(7)
        at.set_color(BG)
    ax.set_title("Kanały płatności", color=FG, fontsize=9, pad=6)
    fig.patch.set_facecolor(BG)
    fig.tight_layout()
    return _to_base64(fig)
