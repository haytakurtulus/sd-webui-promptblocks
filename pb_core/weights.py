import math

DEFAULT_WEIGHT = 1
MAX_WEIGHT = 100


def _is_number(value):
    # bool is a subclass of int; True/False are not weights.
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _check(value):
    # Returns an error message, or None if value is a usable weight.
    if not _is_number(value):
        return "Weight must be a number."
    if not math.isfinite(value):
        return "Weight must be a finite number."
    if value <= 0:
        return "Weight must be greater than 0 (use 1 for normal chance)."
    if value > MAX_WEIGHT:
        return f"Weight must be at most {MAX_WEIGHT}."
    return None


def _normalize(value):
    # 2.0 -> 2 so blocks.json stays readable; 0.5 stays 0.5.
    value = float(value)
    return int(value) if value.is_integer() else value


def block_weight(block):
    # Effective weight used at pick time. Missing or broken values behave as 1, never raise.
    value = block.get("weight", DEFAULT_WEIGHT) if isinstance(block, dict) else DEFAULT_WEIGHT
    if _check(value) is not None:
        return DEFAULT_WEIGHT
    return _normalize(value)


def validate_weight(value):
    # Save-time check: (weight, None) if 0 < weight <= MAX_WEIGHT and finite, else (None, error).
    err = _check(value)
    if err:
        return None, err
    return _normalize(value), None


def is_active(block):
    # Missing "active" = True. Only an explicit boolean False makes a block inactive;
    # broken hand-edited values ("no", 0, None, ...) behave as active and never raise.
    if not isinstance(block, dict):
        return True
    return block.get("active", True) is not False


def in_category(block, category):
    # The one category membership rule: does `%category` (a pick pool, a filter, a count) include this
    # block? Non-dict entries (hand-edited blocks.json) and None are in no category. Reading a block's
    # own category for display is not membership and reads the field directly.
    return isinstance(block, dict) and block.get("category") == category


def category_pool(blocks, category):
    # Names of the active blocks in category, sorted by name: the %Category pick pool.
    # Non-dict entries (hand-edited blocks.json) are never in a pool.
    return sorted(k for k, b in blocks.items()
                  if in_category(b, category) and is_active(b))


def chances(blocks, category):
    # {name: fraction} for every active block in category; fractions sum to 1.
    # {} for an empty category or one whose blocks are all inactive.
    pool = {k: block_weight(blocks[k]) for k in category_pool(blocks, category)}
    total = sum(pool.values())
    if not pool or total <= 0:
        return {}
    return {k: w / total for k, w in sorted(pool.items())}


def _fmt(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


def chance_line(blocks, name, category):
    # One-line Markdown for the management tab, e.g.
    # "Chance in `%PCharacter`: 40% (weight 2 of 5)". "" if the block is not in the category.
    from .parser import CATEGORY_SYMBOL
    block = blocks.get(name)
    if in_category(block, category) and not is_active(block):
        return f"Inactive: not in `{CATEGORY_SYMBOL}{category}` picks"
    fractions = chances(blocks, category)
    if name not in fractions:
        return ""
    total = sum(block_weight(blocks[k]) for k in fractions)
    return (f"Chance in `{CATEGORY_SYMBOL}{category}`: {_fmt(fractions[name] * 100)}% "
            f"(weight {_fmt(block_weight(blocks[name]))} of {_fmt(total)})")
