"""Deterministyczne dane demonstracyjne dla dwóch trybów dopasowania gmin.

Profile kategorii są syntetyczne. Jedyną rzeczywistą cechą używaną tutaj
jest odległość między centroidami gmin z GeoJSON.
"""

from dataclasses import dataclass
from hashlib import sha256
from math import asin, cos, radians, sin, sqrt


CATEGORIES = (
    "Żywność",
    "Zdrowie",
    "Gastronomia",
    "Usługi",
    "Transport",
    "Kultura i czas wolny",
)
MODES = ("Wzmocnienie", "Uzupełnienie")


@dataclass(frozen=True)
class Match:
    gmina: str
    score: int
    distance_km: float
    category: str


def _profile(gmina: str) -> tuple[float, ...]:
    """Stały profil demo dla nazwy gminy; nie pochodzi z transakcji."""
    digest = sha256(gmina.encode("utf-8")).digest()
    return tuple(0.15 + byte / 255 * 0.8 for byte in digest[:len(CATEGORIES)])


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
    """Ranking demo: wspólne mocne kategorie lub uzupełnianie słabości.

    Wynik 0–100 ma znaczenie tylko w tym demonstracyjnym rankingu.
    """
    if mode not in MODES:
        raise ValueError(f"Nieznany tryb: {mode}")
    if anchor not in centroids:
        raise ValueError(f"Nieznana gmina: {anchor}")

    anchor_profile = _profile(anchor)
    results = []
    for gmina, point in centroids.items():
        if gmina == anchor:
            continue
        distance = _distance_km(centroids[anchor], point)
        if distance > max_distance_km:
            continue

        candidate = _profile(gmina)
        if mode == "Wzmocnienie":
            shared = [min(a, b) for a, b in zip(anchor_profile, candidate)]
            profile_score = 0.7 * sum(shared) / len(shared) + 0.3 * (
                1 - sum(abs(a - b) for a, b in zip(anchor_profile, candidate)) / len(shared)
            )
            category = CATEGORIES[max(range(len(shared)), key=shared.__getitem__)]
        else:
            gaps = [max(b - a, 0) * (1 - a) for a, b in zip(anchor_profile, candidate)]
            strongest = sorted(gaps, reverse=True)[:2]
            profile_score = min(1, 2.5 * sum(strongest) / len(strongest))
            category = CATEGORIES[max(range(len(gaps)), key=gaps.__getitem__)]

        proximity = 1 - distance / max_distance_km
        score = round(100 * (0.8 * profile_score + 0.2 * proximity))
        results.append(Match(gmina, score, round(distance, 1), category))

    return sorted(results, key=lambda match: (-match.score, match.distance_km, match.gmina))[:limit]
