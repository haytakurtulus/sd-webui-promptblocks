"""Block seed helper: maps the "Block seed" field value to per-image RNG seeds.

Pure Python, no WebUI / gradio imports.
"""
import math
import random

SEED_RANGE = 2**32


def normalize_block_seed(value):
    """Return a fixed non-negative int seed, or None when a random seed should be used.

    None, negative numbers, bools, NaN/inf and non-numbers all mean "random" (like -1).
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    value = int(value)
    return value if value >= 0 else None


def block_seeds(block_seed, n_images, rng=None):
    """Return (base, seeds) where seeds[i] = base + i for i in range(n_images).

    A fixed (non-negative) block_seed is used as base. Otherwise ONE random base is drawn
    from `rng` (default: the module-level `random`), so image i uses base + i.
    """
    base = normalize_block_seed(block_seed)
    if base is None:
        base = (rng or random).randrange(SEED_RANGE)
    return base, [base + i for i in range(max(0, int(n_images)))]
