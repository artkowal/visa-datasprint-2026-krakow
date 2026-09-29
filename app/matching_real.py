"""Ranking partnerów gmin oparty na rzeczywistych profilach kategorii."""

from math import asin, cos, radians, sin, sqrt
from pathlib import Path

from app.matching_demo import Match
from app.categories import GROUP_ORDER

_EXCLUDED = {"Handel internetowy", "Inne"}
CATEGORIES = [g for g in GROUP_ORDER if g not in _EXCLUDED]
_BY_CAT_PATH = Path("dataset/json/by_category.json")
_DOMINANT_PATH = Path("dataset/json/t_dominant.json")


def _load_profiles() -> dict[str, tuple[float, ...]]:
    """Ładuje profile kategorii. Używa by_category.json gdy dostępny, inaczej t_dominant."""
    import json
    if _BY_CAT_PATH.exists():
        data = json.loads(_BY_CAT_PATH.read_text(encoding="utf-8"))
        return {
            gmina: tuple(shares.get(cat, 0.0) for cat in CATEGORIES)
            for gmina, shares in data.items()
        }
    if _DOMINANT_PATH.exists():
        raw = json.loads(_DOMINANT_PATH.read_text(encoding="utf-8"))
        profiles: dict[str, tuple[float, ...]] = {}
        for gmina, rows in raw["data"].items():
            if not rows:
                continue
            grupa = rows[0][0]  # cols: [grupa, n, pct, avg_amt]
            profiles[gmina] = tuple(1.0 if cat == grupa else 0.0 for cat in CATEGORIES)
        return profiles
    return {}


def load_display_profiles() -> dict[str, dict[str, float]]:
    """Returns {gmina: {category: share}} for visualization."""
    import json
    if _BY_CAT_PATH.exists():
        data = json.loads(_BY_CAT_PATH.read_text(encoding="utf-8"))
        return {
            gmina: {cat: float(shares.get(cat, 0.0)) for cat in CATEGORIES}
            for gmina, shares in data.items()
        }
    if _DOMINANT_PATH.exists():
        raw = json.loads(_DOMINANT_PATH.read_text(encoding="utf-8"))
        profiles: dict[str, dict[str, float]] = {}
        for gmina, rows in raw["data"].items():
            if rows:
                grupa = rows[0][0]
                profiles[gmina] = {cat: (1.0 if cat == grupa else 0.0) for cat in CATEGORIES}
        return profiles
    return {}


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

    results = []
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
            # Wysoki wynik gdy obie gminy mają silne te same kategorie
            shared = [min(a, b) for a, b in zip(anchor_profile, candidate)]
            profile_score = sum(shared)
            best_idx = max(range(len(shared)), key=shared.__getitem__)
            category = CATEGORIES[best_idx]
        else:
            # Uzupełnienie: anchor słaby w X, kandydat silny w X (i odwrotnie)
            # anchor_weak * candidate_strong + candidate_weak * anchor_strong
            complement = [
                (1 - a) * b + (1 - b) * a
                for a, b in zip(anchor_profile, candidate)
            ]
            profile_score = sum(sorted(complement, reverse=True)[:3]) / 3
            best_idx = max(range(len(complement)), key=complement.__getitem__)
            category = CATEGORIES[best_idx]

        proximity = 1 - distance / max_distance_km
        score = round(100 * (0.8 * min(profile_score, 1.0) + 0.2 * proximity))
        results.append(Match(gmina, score, round(distance, 1), category))

    return sorted(results, key=lambda m: (-m.score, m.distance_km, m.gmina))[:limit]
