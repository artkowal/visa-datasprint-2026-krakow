"""Ranking partnerów gmin oparty na rzeczywistych profilach kategorii."""

from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from app.matching_demo import Match
from app.categories import GROUP_ORDER

_EXCLUDED = {"Handel internetowy", "Inne"}
CATEGORIES = [g for g in GROUP_ORDER if g not in _EXCLUDED]

# Kategorie wykluczone z algorytmu rankingu — ubiquitous, nie różnicują gmin
_MATCH_EXCLUDED = _EXCLUDED | {"Żywność", "Zdrowie i apteki", "Dyskonty i domy towarowe"}
_MATCH_CATEGORIES = [g for g in GROUP_ORDER if g not in _MATCH_EXCLUDED]
_BY_CAT_PATH = Path("dataset/json/by_category.json")
_DOMINANT_PATH = Path("dataset/json/t_dominant.json")


def _read_json(path: Path):
    """Wczytuje JSON z pliku; zwraca None gdy plik brak, pusty lub uszkodzony."""
    import json
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else None
    except (json.JSONDecodeError, OSError):
        return None


def _load_raw(cats: list[str] = None) -> dict[str, tuple[float, ...]]:
    """Surowe udziały kategorii per gmina."""
    if cats is None:
        cats = CATEGORIES
    data = _read_json(_BY_CAT_PATH)
    if isinstance(data, dict) and data:
        return {g: tuple(shares.get(c, 0.0) for c in cats) for g, shares in data.items()}
    raw = _read_json(_DOMINANT_PATH)
    if isinstance(raw, dict) and "data" in raw:
        out: dict[str, tuple[float, ...]] = {}
        for g, rows in raw["data"].items():
            if rows:
                grp = rows[0][0]
                out[g] = tuple(1.0 if c == grp else 0.0 for c in cats)
        return out
    return {}


def _normalize(raw: dict[str, tuple[float, ...]]) -> dict[str, tuple[float, ...]]:
    """Odejmuje per-kategorię średnią rynkową → profil odchyleń od normy."""
    if not raw:
        return raw
    n = len(raw)
    nc = len(next(iter(raw.values())))
    means = [sum(p[i] for p in raw.values()) / n for i in range(nc)]
    return {g: tuple(p[i] - means[i] for i in range(nc)) for g, p in raw.items()}


def _load_profiles() -> dict[str, tuple[float, ...]]:
    """Profile znormalizowane bez kategorii ubiquitous — do rankingu."""
    return _normalize(_load_raw(cats=_MATCH_CATEGORIES))


def load_display_profiles(matching_only: bool = False) -> dict[str, dict[str, float]]:
    """Udziały {gmina: {kategoria: udział}} renormalizowane do wybranych kategorii."""
    cats = _MATCH_CATEGORIES if matching_only else CATEGORIES
    raw = _load_raw(cats=cats)
    result = {}
    for g, p in raw.items():
        total = sum(p) or 1.0
        result[g] = {c: v / total for c, v in zip(cats, p)}
    return result


def load_normalized_profiles() -> dict[str, dict[str, float]]:
    """Odchylenia od średniej rynkowej — do logiki dopasowań i _key_pairs."""
    norm = _normalize(_load_raw())
    return {g: dict(zip(CATEGORIES, p)) for g, p in norm.items()}


def _distance_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(h))


def rank_matches(
    anchor: str,
    centroids: dict[str, tuple[float, float]],
    mode: str,
    max_distance_km: int = 150,
    limit: int = 5,
) -> list[Match]:
    profiles = _load_profiles()
    anchor_profile = profiles.get(anchor)
    if not anchor_profile:
        from app.matching_demo import rank_matches as demo_rank
        return demo_rank(anchor, centroids, mode, max_distance_km, limit)

    raw: list[tuple[str, str, float, float, float]] = []
    for gmina, point in centroids.items():
        if gmina == anchor:
            continue
        distance = _distance_km(centroids[anchor], point)
        if distance > max_distance_km:
            continue

        candidate = profiles.get(gmina)
        if not candidate:
            continue

        if mode == "Wzmocnienie":
            shared = [max(0.0, min(a, b)) for a, b in zip(anchor_profile, candidate)]
            profile_score = sum(shared)
            best_idx = max(range(len(shared)), key=shared.__getitem__)
            category = _MATCH_CATEGORIES[best_idx]
        else:
            complement = [
                max(0.0, a) * max(0.0, -b) + max(0.0, b) * max(0.0, -a)
                for a, b in zip(anchor_profile, candidate)
            ]
            profile_score = sum(sorted(complement, reverse=True)[:3]) / 3
            best_idx = max(range(len(complement)), key=complement.__getitem__)
            category = _MATCH_CATEGORIES[best_idx]

        proximity = 1 - distance / max_distance_km
        raw.append((gmina, category, profile_score, distance, proximity))

    if not raw:
        return []

    # Normalizacja względem najlepszego kandydata — najlepszy profil = 1.0
    max_ps = max(r[2] for r in raw) or 1e-9
    results = []
    for gmina, category, ps, distance, proximity in raw:
        normalized = ps / max_ps
        score = round(100 * (0.8 * normalized + 0.2 * proximity))
        results.append(Match(gmina, score, round(distance, 1), category))

    return sorted(results, key=lambda m: (-m.score, m.distance_km, m.gmina))[:limit]
