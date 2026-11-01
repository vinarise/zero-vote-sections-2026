"""Intervals used by the ledger."""
import math
from statistics import NormalDist

Z95 = NormalDist().inv_cdf(0.975)  # 1.959963984540054


def wilson(k, n, z=Z95):
    """Wilson score interval for k successes in n trials. Returns (low, high).

    n = 0 gives (nan, nan): a proportion with no denominator has no interval.
    """
    if n is None or n == 0:
        return (math.nan, math.nan)
    if k < 0 or k > n:
        raise ValueError(f"wilson: k={k} outside 0..n={n}")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    lo, hi = centre - half, centre + half
    # The exact ends at k = 0 and k = n, so rounding never gives -1e-17 or 1 + 1e-16.
    return (0.0 if k == 0 else max(0.0, lo), 1.0 if k == n else min(1.0, hi))
