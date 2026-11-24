"""ADetailer text per block, Stage 1 (design notes sections 31 and 31a).

Pure Python, no WebUI / gradio imports. Everything that does not need WebUI lives here and is tested
with plain objects: the stored field, the additions per image and ADetailer tab, assign(), and the
runtime hook on ADetailer's script instance (wrappers built from the original bound methods).

Stored shape: optional block field "adetailer": [t1, t2, t3, t4] (one text per ADetailer tab 1st..4th).
Missing / broken = four empty texts; stored only when at least one text is non-empty (key removed
otherwise), always as exactly four stripped strings.

Data flow at Generate (scripts/promptblocks.py): the positive prompt of image i is expanded with
parser.expand(..., uses=[...]); image_additions(blocks, uses_i, seed_i) turns that list into the
additions per tab, a list of (block name, resolved text) (section 31a rule 2: not pre-joined); the table
of all images is stored on `p` (P_ATTR). The hook appends them to the prompt parts ADetailer's own
get_prompt() returned, with assign().
"""
import functools
import inspect
import random
import re

from . import bans as ban_rules, lora, parser

FIELD = "adetailer"
TABS = 4
TAB_LABELS = ("1st", "2nd", "3rd", "4th")
JOINER = ", "

# ADetailer's own [SKIP] rule (scripts/!adetailer.py, _postprocess_image_inner): a part that is only
# "[SKIP]" skips that face. Such a part must stay exactly as it is.
_SKIP = re.compile(r"^\s*\[SKIP\]\s*$")

# Runtime hook (section 31a).
ADETAILER_TITLE = "ADetailer"
P_ATTR = "_promptblocks_ad_additions"  # on the processing object: per image, per tab, [(name, text)]
# On the processing object (design notes 34 B): {job-wide image index: per tab [(name, text)]} of what the
# hook REALLY appended; None = nothing can be recorded (no additions stored for this run).
APPLIED_ATTR = "_promptblocks_ad_applied"
HOOK_MARKER = "_promptblocks_ad_hook"   # on the ADetailer script instance: the hook state, or FAILED
FAILED = "failed"
WARN_PREFIX = "[PromptBlocks] ADetailer hook disabled: "

# Infotext (design notes 33 F): per-image list of what is appended, information only (not pasted back).
INFOTEXT_KEY = "PromptBlocks ADetailer"

# Design notes 35 "Keep main LoRAs in ADetailer": on the processing object a LoraSync (checkbox on and an
# ADetailer instance hooked) or None. Independent of P_ATTR: it also works without any block.
LORA_SYNC_ATTR = "_promptblocks_ad_lora_sync"
LORA_SYNC_INFOTEXT_KEY = "PromptBlocks ADetailer LoRA sync"
LORA_SYNC_VALUE = "on"
SYNC_WARN_PREFIX = "[PromptBlocks] ADetailer LoRA sync disabled: "
# ADetailer's "use same checkpoint" values (scripts/!adetailer.py get_override_settings).
_SAME_CHECKPOINT = (None, "", "None", "Use same checkpoint")


# ---- stored field ----

def block_adetailer(block):
    """The block's four ADetailer texts, stripped; missing / broken values give "" (a non-list field, a
    non-string entry, missing entries). Entries after the fourth are ignored. Never raises."""
    raw = block.get(FIELD) if isinstance(block, dict) else None
    if not isinstance(raw, list):
        raw = []
    result = []
    for i in range(TABS):
        v = raw[i] if i < len(raw) else ""
        result.append(v.strip() if isinstance(v, str) else "")
    return result


def clean_texts(texts):
    """Form values -> four stripped strings (None / non-strings count as ""; missing entries are "")."""
    texts = list(texts or [])[:TABS]
    texts += [""] * (TABS - len(texts))
    return [t.strip() if isinstance(t, str) else "" for t in texts]


def set_block_adetailer(block, texts):
    """New block dict with "adetailer" set to clean_texts(texts), or without the key when all four are
    empty (old JSON shape). The input is not modified."""
    block = dict(block)
    cleaned = clean_texts(texts)
    if any(cleaned):
        block[FIELD] = cleaned
    else:
        block.pop(FIELD, None)
    return block


def adetailer_texts(block):
    """[(tab index 0..3, text)] of the block's non-empty ADetailer texts."""
    return [(k, t) for k, t in enumerate(block_adetailer(block)) if t]


def tab_label(k):
    return TAB_LABELS[k] if 0 <= k < len(TAB_LABELS) else str(k + 1)


def ignored_details(block, show=repr):
    """Health check texts for stored ADetailer values that are ignored: a field that is not a list,
    entries that are not text, non-empty entries after the fourth. [] when all is fine. None / missing
    count as "not set". `show(value)` formats a stored value (the health check passes its own)."""
    if not isinstance(block, dict) or block.get(FIELD) is None:
        return []
    raw = block[FIELD]
    if not isinstance(raw, list):
        return [f"adetailer {show(raw)} is not a list of {TABS} texts; no ADetailer text is used"]
    result = []
    for i, v in enumerate(raw):
        if i >= TABS:
            if v not in (None, "") and not (isinstance(v, str) and not v.strip()):
                result.append(f"adetailer entry #{i + 1} is ignored: only {TABS} tabs are used")
            continue
        if v is not None and not isinstance(v, str):
            result.append(f"adetailer {tab_label(i)} {show(v)} is not text; ignored")
    return result


def rewrite_texts(block, fn):
    """(new "adetailer" list, changed) with fn(text) applied to every string entry of the stored list
    (other entries are kept as they are). (None, False) when the field is not a list."""
    raw = block.get(FIELD) if isinstance(block, dict) else None
    if not isinstance(raw, list):
        return None, False
    new, changed = [], False
    for v in raw:
        if isinstance(v, str):
            t = fn(v)
            changed = changed or t != v
            new.append(t)
        else:
            new.append(v)
    return new, changed


# ---- block uses -> additions ----

def used_blocks(uses):
    """Block names of a parser.expand(uses=...) list: each once, in order of first use."""
    seen, result = set(), []
    for u in uses or []:
        name = u.get("block") if isinstance(u, dict) else None
        if isinstance(name, str) and name not in seen:
            seen.add(name)
            result.append(name)
    return result


def category_picks(uses):
    """{category: block} of the FIRST %category pick at any depth in a uses list (section 31a)."""
    result = {}
    for u in uses or []:
        if isinstance(u, dict) and u.get("via") == "category":
            c, b = u.get("category"), u.get("block")
            if isinstance(c, str) and isinstance(b, str) and c not in result:
                result[c] = b
    return result


def resolve_text(text, blocks, seed, forced, bans=None, ban_events=None):
    """One ADetailer text with its tokens expanded (section 31a): %Category -> the block that category
    picked in this image's prompt (`forced`, at any depth), everything else with a fresh
    random.Random(seed). No block LoRA. Only normal block texts are reached, so no ADetailer text is
    added recursively. May raise parser.BlockCycleError.
    Section 38 step 4: `bans` ({banner: tokens}, the image's ban set) is active from the start, so banned
    ~b / ~b.sub / ~b*slot / %C tokens are silenced (separators cleaned) and a banned forced pick silences
    its %C token; bans of blocks reached by the text itself apply as in the main prompt. No bans at all
    -> exactly the plain expansion. `ban_events`: as in parser.expand."""
    return parser.expand(text, blocks, random.Random(seed), lora=False, forced=forced, bans=bans,
                         ban_events=ban_events).strip()


def image_additions(blocks, uses, seed, errors=None, ban_events=None):
    """Additions of one image: a list of TABS lists, tab k = [(block name, resolved text), ...] for every
    block in `uses` (order of first use, each once) whose tab-k ADetailer text is non-empty and resolves
    to a non-empty text. `seed` is the image's block seed. A text whose expansion raises
    BlockCycleError is skipped; if `errors` is a list, a message is appended for it.
    Section 38 step 4: each text is resolved under the image's ban set (bans.used_bans(blocks, uses)),
    including the block's own bans (they filter its own ADetailer text like its main text; a ~block token
    is still never silenced by that block's own bans). A text that is empty after silencing adds nothing. `ban_events`: if a list, the ban effects of every resolved
    text are appended to it."""
    forced = category_picks(uses)
    image_bans = ban_rules.used_bans(blocks, uses)
    result = [[] for _ in range(TABS)]
    for name in used_blocks(uses):
        block = blocks.get(name) if isinstance(blocks, dict) else None
        if not isinstance(block, dict):
            continue
        texts = adetailer_texts(block)
        if not texts:
            continue
        for k, raw in texts:
            try:
                text = resolve_text(raw, blocks, seed, forced, image_bans, ban_events)
            except parser.BlockCycleError as e:
                if errors is not None:
                    errors.append(f"{parser.BLOCK_SYMBOL}{name} ADetailer {tab_label(k)}: {e}")
                continue
            if text:
                result[k].append((name, text))
    return result


def all_additions(blocks, uses_per_image, seeds, errors=None):
    """image_additions for every image (index-aligned lists of uses and block seeds; each image with its
    own ban set, section 38 step 4), or None when no image has any addition (nothing to store on `p`)."""
    table = [image_additions(blocks, u, s, errors) for u, s in zip(uses_per_image, seeds)]
    return table if any(any(tab) for tab in table) else None


def preview_ban_lines(events):
    """Preview lines (section 38 step 4) for the ban effects inside the ADetailer texts, e.g.
    "⛔ ADetailer: ninja: %PEmotion silenced"; [] when none."""
    return ban_rules.ban_lines(events, prefix="⛔ ADetailer: ")


def assign(parts, additions):
    """Stage 1 (section 31a): the prompt parts of one ADetailer tab (get_prompt() split on [SEP]) with
    the additions appended to EVERY part. The texts are joined with ", " in their order; a part gets
    ", " + joined (just " " + joined after a trailing comma); an empty part (only possible when the main
    prompt itself is empty, since ADetailer replaces empty parts with it) becomes the joined text; a
    "[SKIP]" part stays unchanged. No additions -> an unchanged copy. A new list is returned."""
    texts = [t for _, t in additions or [] if isinstance(t, str) and t.strip()]
    if not texts:
        return list(parts)
    joined = JOINER.join(t.strip() for t in texts)
    result = []
    for part in parts:
        if _SKIP.match(part):
            result.append(part)
        elif not part.strip():
            result.append(joined)
        else:
            base = part.rstrip()
            result.append(base + (" " if base.endswith(",") else JOINER) + joined)
    return result


# ---- "Keep main LoRAs in ADetailer" (design notes 35) ----

def _sync_part(part, tags):
    # One part: its own LoRA tags removed (rest as written), then the source tags appended with the
    # same joining as assign(). A part whose tags already ARE the source tags (verbatim, same order) is
    # left exactly as it is: the loaded LoRA list would be the same, and the text must not move around.
    if lora.lora_tags_in_order(part) == tags:
        return part
    base = lora.strip_lora_tags(part)
    if not tags:
        return base
    joined = JOINER.join(tags)
    stripped = base.rstrip()
    if not stripped.strip():
        return joined
    return stripped + (" " if stripped.endswith(",") else JOINER) + joined


def sync_loras(parts, source_text):
    """Design notes 35: the prompt parts of one ADetailer tab with every part's own <lora:...> /
    <lyco:...> tags replaced by those of `source_text` (verbatim, in order, duplicates kept), appended
    with ", ". "[SKIP]" parts and parts that already carry exactly the source tags stay unchanged; a
    source without tags removes the parts' tags. A new list is returned."""
    tags = lora.lora_tags_in_order(source_text)
    return [part if _SKIP.match(part) else _sync_part(part, tags) for part in parts]


def lora_source(p):
    """The prompt whose LoRAs are loaded while ADetailer runs (design notes 35 rule 2): Forge activates
    extra networks per batch from the batch's FIRST prompt, and the hires pass re-activates those of the
    hires prompts. So all_hr_prompts (hires on and the list non-empty) else all_prompts, at index
    iteration * batch_size. None when anything is missing, broken or out of range (no sync)."""
    try:
        hr = getattr(p, "all_hr_prompts", None)
        src = hr if getattr(p, "enable_hr", False) and hr else getattr(p, "all_prompts", None)
        if not isinstance(src, (list, tuple)):
            return None
        it, bs = p.iteration, p.batch_size
        if any(isinstance(x, bool) or not isinstance(x, int) for x in (it, bs)):
            return None
        idx = it * bs
        if not (0 <= idx < len(src)):
            return None
        text = src[idx]
        return text if isinstance(text, str) else None
    except Exception:
        return None


def uses_own_checkpoint(args):
    """True when the ADetailer tab `args` runs with its own checkpoint (ADetailer get_override_settings:
    ad_use_checkpoint on and ad_checkpoint not "None" / "Use same checkpoint"): its LoRA set is left
    alone (design notes 35 rule 4)."""
    return bool(getattr(args, "ad_use_checkpoint", False)) and \
        getattr(args, "ad_checkpoint", None) not in _SAME_CHECKPOINT


class LoraSync:
    """On `p` while "Keep main LoRAs in ADetailer" is active for the run. `changed` = {job-wide image
    index: True} for images where the sync changed at least one part; `infotext` = the value process()
    wants under LORA_SYNC_INFOTEXT_KEY (put into p.extra_generation_params by the hook on the first
    change, so a run without a change has no key at all)."""

    def __init__(self, infotext=None):
        self.changed = {}
        self.infotext = infotext


def apply_lora_sync(p, args, parts):
    """The hook's sync step for one get_prompt call: `parts` synced (sync_loras with lora_source(p)) when
    `p` carries a LoraSync, the tab does not use its own checkpoint and a source exists; otherwise
    `parts` unchanged. A change is recorded for the current image and the infotext key is set. May
    raise (the caller falls back to `parts`)."""
    sync = getattr(p, LORA_SYNC_ATTR, None)
    if not isinstance(sync, LoraSync) or uses_own_checkpoint(args):
        return parts
    source = lora_source(p)
    if source is None:
        return parts
    new_parts = sync_loras(parts, source)
    if new_parts == parts:
        return parts
    sync.changed[image_index(p)] = True
    if sync.infotext is not None:
        p.extra_generation_params[LORA_SYNC_INFOTEXT_KEY] = sync.infotext
    return new_parts


# ---- infotext (design notes 33 F) ----

def _one_line(text):
    # Line breaks inside a text would make the infotext harder to read; Forge's quote() would keep the
    # value on one line anyway (JSON escapes), this only makes it readable.
    return re.sub(r"\s*[\r\n]+\s*", " ", text.strip())


def infotext_summary(row):
    """One image's additions (a list of TABS lists of (block name, text)) as one line, e.g.
    "1st: (blue skin), (closed eyes); 2nd: long hair": per tab that has additions, its label and the
    texts joined with ", " (the same joining as assign()). "" when nothing is added."""
    parts = []
    for k, items in enumerate(row or []):
        texts = [_one_line(t) for _, t in items or [] if isinstance(t, str) and t.strip()]
        if texts:
            parts.append(f"{tab_label(k)}: " + JOINER.join(texts))
    return "; ".join(parts)


# ---- preview (POST /promptblocks/preview) ----

def preview_entries(additions):
    """[{"tab": 1..4, "label": "1st", "items": [{"block", "text"}]}] for the tabs that have additions."""
    return [{"tab": k + 1, "label": tab_label(k), "items": [{"block": n, "text": t} for n, t in items]}
            for k, items in enumerate(additions) if items]


def preview_warnings(additions, blocks, unknown, all_inactive):
    """`unknown` / `all_inactive` (the main prompt's warnings) extended by those of the resolved addition
    texts (parser.preview_warnings), without duplicates. New lists are returned."""
    unknown, all_inactive = list(unknown), list(all_inactive)
    for items in additions:
        for _, text in items:
            u, a = parser.preview_warnings(text, blocks)
            unknown += [x for x in u if x not in unknown]
            all_inactive += [x for x in a if x not in all_inactive]
    return unknown, all_inactive


# ---- runtime hook on ADetailer's script instance ----

class HookState:
    """Shared by the two wrappers of one ADetailer instance: the tab index `n` of the running
    _postprocess_image_inner call (None outside it) and whether the hook switched itself off."""

    def __init__(self):
        self.n = None
        self.disabled = False
        self.sync_disabled = False  # design notes 35: the LoRA sync switched itself off (error)


def image_index(p):
    """ADetailer's image index (aaaaaa/p_method.get_i): iteration * batch_size + batch_index."""
    return p.iteration * p.batch_size + p.batch_index


def additions_for(p, n):
    """The [(name, text)] list stored on `p` for the current image and ADetailer tab n ([] if none)."""
    table = getattr(p, P_ATTR, None)
    if not table:
        return []
    i = image_index(p)
    if not (0 <= i < len(table)):
        return []
    row = table[i]
    if isinstance(n, bool) or not isinstance(n, int) or not (0 <= n < len(row)):
        return []
    return row[n]


def make_inner_wrapper(original, state):
    """Wrapper of ADetailer's bound `_postprocess_image_inner(p, pp, args, *, n=0)`: remembers n for the
    get_prompt calls made inside it, then calls the original unchanged (its result and its exceptions
    pass through)."""
    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        state.n = kwargs.get("n", 0)
        try:
            return original(*args, **kwargs)
        finally:
            state.n = None
    return wrapper


def record_applied(p, n, additions):
    """Design notes 34 B: note on `p` (APPLIED_ATTR dict, created by process()) that the additions of
    ADetailer tab n were appended for the current image. No dict on `p` -> nothing recorded."""
    record = getattr(p, APPLIED_ATTR, None)
    if not isinstance(record, dict) or not (0 <= n < TABS):
        return
    row = record.setdefault(image_index(p), [[] for _ in range(TABS)])
    row[n] = list(additions)


def make_get_prompt_wrapper(original, state, warn=print):
    """Wrapper of ADetailer's bound `get_prompt(p, args)` -> (prompt parts, negative parts). Only inside
    a _postprocess_image_inner call (n remembered) and when additions exist for (image, n), the prompt
    parts go through assign() and what was appended is recorded on `p` (record_applied, for the
    infotext); negatives are untouched. Then (design notes 35) when `p` carries a LoraSync, the parts'
    LoRA tags are replaced by the main prompt's (apply_lora_sync), also for a tab without additions.
    Calls without n (ADetailer's process() with an X/Y/Z prompt S/R) are passed through. Any exception
    in the additions part: one console line, the hook of this instance switches off, and the original
    result is returned. Any exception in the sync: one console line, the sync of this instance switches
    off, and the parts as they were before the sync are returned. Exceptions of the original pass
    through."""
    @functools.wraps(original)
    def wrapper(p, *args, **kwargs):
        result = original(p, *args, **kwargs)
        n = state.n
        if n is None or state.disabled:
            return result
        try:
            adds = additions_for(p, n)
            sync = not state.sync_disabled and isinstance(getattr(p, LORA_SYNC_ATTR, None), LoraSync)
            if not adds and not sync:
                return result
            parts, negatives = result
            if not isinstance(parts, list) or not all(isinstance(x, str) for x in parts):
                raise TypeError(f"unexpected prompt parts {type(parts).__name__}")
            if adds:
                new_parts = assign(parts, adds)
                record_applied(p, n, adds)
            else:
                new_parts = parts
        except Exception as e:
            state.disabled = True
            warn(WARN_PREFIX + f"{type(e).__name__}: {e}")
            return result
        if sync:
            try:
                ad_args = args[0] if args else kwargs.get("args")
                new_parts = apply_lora_sync(p, ad_args, new_parts)
            except Exception as e:
                state.sync_disabled = True
                warn(SYNC_WARN_PREFIX + f"{type(e).__name__}: {e}")
        if new_parts is parts:
            return result
        return new_parts, negatives
    return wrapper


def _positional(sig):
    kinds = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return [x for x in sig.parameters.values() if x.kind in kinds]


def signature_problem(script):
    """Why the ADetailer instance `script` cannot be hooked, or None. Expected (bound methods):
    _postprocess_image_inner(p, pp, args, *, n=0) and get_prompt(p, args)."""
    inner = getattr(script, "_postprocess_image_inner", None)
    get_prompt = getattr(script, "get_prompt", None)
    if not callable(inner) or not callable(get_prompt):
        return "_postprocess_image_inner / get_prompt not found"
    try:
        si, sg = inspect.signature(inner), inspect.signature(get_prompt)
    except (TypeError, ValueError) as e:
        return f"signature not readable ({e})"
    if len(_positional(si)) < 3 or "n" not in si.parameters:
        return f"unexpected signature _postprocess_image_inner{si}"
    if len(_positional(sg)) < 2:
        return f"unexpected signature get_prompt{sg}"
    return None


def install(script, warn=print):
    """Hook one ADetailer script instance once (marker attribute HOOK_MARKER; idempotent). Returns True
    when the instance is hooked (now or before). A missing method / unexpected signature / any error:
    one console line, the instance is marked FAILED (no second warning) and left unchanged, False."""
    marker = getattr(script, HOOK_MARKER, None)
    if marker is not None:
        return isinstance(marker, HookState)
    try:
        problem = signature_problem(script)
        if problem:
            raise RuntimeError(problem)
        state = HookState()
        inner, get_prompt = script._postprocess_image_inner, script.get_prompt
        script.get_prompt = make_get_prompt_wrapper(get_prompt, state, warn)
        script._postprocess_image_inner = make_inner_wrapper(inner, state)
        setattr(script, HOOK_MARKER, state)
        return True
    except Exception as e:
        try:
            setattr(script, HOOK_MARKER, FAILED)
        except Exception:
            pass
        warn(WARN_PREFIX + str(e))
        return False


def find_scripts(runners):
    """ADetailer script instances (title "ADetailer") in the given WebUI ScriptRunner objects (their
    `scripts` and `alwayson_scripts` lists), each once. None runners and broken entries are skipped."""
    found, seen = [], set()
    for runner in runners:
        for attr in ("alwayson_scripts", "scripts"):
            for s in getattr(runner, attr, None) or []:
                if id(s) in seen:
                    continue
                seen.add(id(s))
                try:
                    if s.title() == ADETAILER_TITLE:
                        found.append(s)
                except Exception:
                    continue
    return found


def install_all(runners, warn=print):
    """install() on every ADetailer instance of `runners`. Returns the number of hooked instances
    (0: ADetailer not installed, or its hook failed)."""
    return sum(1 for s in find_scripts(runners) if install(s, warn))
