"""The work of Script.process() at Generate (CLAUDE.md "Architecture", design notes 15, 31a, 33).

Pure Python, no WebUI / gradio imports: scripts/promptblocks.py passes the WebUI parts in (the block
loader, the ADetailer hook installer, console output), so this module is tested with fake `p` objects.

Re-run guard (design notes 33 A): ADetailer calls `p.scripts.process(copy(p))` once more at the last batch
index, on prompts this module already expanded. A `p` that carries our marker (copy() keeps attributes)
and whose prompt lists are still exactly the ones we produced is left alone: no expansion, no change to
state.last_picks / state.last_generated, infotext or the ADetailer table. A new Generate has a new `p`
(no marker). A script that runs process_images() again on the SAME `p` (Loopback, SD upscale,
Outpainting) gets fresh template prompts from p.setup_prompts(), which differ from the marker, so it is
expanded normally. The marker is also set when no blocks are loaded or a BlockCycleError left the
prompts unchanged (design notes 35: the copy shares extra_generation_params, and its re-run must not
remove the "PromptBlocks ADetailer LoRA sync" key the hook wrote).

Per-image infotext (design notes 34): Forge's create_infotext() is called with an index INSIDE the batch
(PNG text of every image, `all_prompts` = the batch slice) and elsewhere with the job-wide index (`all_prompts`
= the full list), so a plain list value would show batch 1's entries on later batches. Per-image keys are
therefore ImageInfotext callables that map the index first (image_index()).
"""
import random

from . import adetailer, bans, parser, picks, seeds, state

SEED_INFOTEXT_KEY = "PromptBlocks seed"
PICKS_INFOTEXT_KEY = "PromptBlocks picks"
TEMPLATE_INFOTEXT_KEY = "PromptBlocks template"
ADETAILER_INFOTEXT_KEY = adetailer.INFOTEXT_KEY
LORA_SYNC_INFOTEXT_KEY = adetailer.LORA_SYNC_INFOTEXT_KEY

DONE_ATTR = "_promptblocks_done"  # on `p`: the prompt lists as process() left them
_PROMPT_LISTS = ("all_prompts", "all_negative_prompts", "all_hr_prompts", "all_hr_negative_prompts")


def _noop(*_args):
    pass


def image_index(p, index, all_prompts):
    """Job-wide image index for a create_infotext() call (design notes 34 A): `index` as is when
    `all_prompts` is the full list (Processed.infotext, before-highres save, ADetailer's own save), else
    p.iteration * p.batch_size + index (the PNG text of each image: `all_prompts` = p.prompts, the batch
    slice). Batch count 1: both are the same. None when anything is missing, broken or out of range."""
    try:
        if isinstance(index, bool) or not isinstance(index, int):
            return None
        total = len(p.all_prompts)
        if len(all_prompts) == total:
            g = index
        else:
            it, bs = p.iteration, p.batch_size
            if any(isinstance(x, bool) or not isinstance(x, int) for x in (it, bs)):
                return None
            g = it * bs + index
        return g if 0 <= g < total else None
    except Exception:
        return None


class ImageInfotext:
    """Per-image value of an extra_generation_params key, as a callable for Forge's create_infotext()
    (called with **locals(): p, index, all_prompts, ...). `values` is a plain list (job-wide index ->
    value) or a dict (job-wide index -> raw entry, filled later, e.g. by the ADetailer hook); `fmt`
    turns a raw entry into the text. Empty / missing / any error -> None (key omitted for that image);
    never raises. Not a list subclass on purpose (Forge checks isinstance(value, list) first).
    Processed.js() serialises a callable as null, so the API does not break."""

    def __init__(self, values, fmt=None):
        self.values = values
        self.fmt = fmt

    def value_at(self, g):
        try:
            if g is None:
                return None
            if isinstance(self.values, dict):
                v = self.values.get(g)
            elif 0 <= g < len(self.values):
                v = self.values[g]
            else:
                return None
            if self.fmt is not None and v is not None:
                v = self.fmt(v)
            return v or None
        except Exception:
            return None

    def __call__(self, p=None, index=None, all_prompts=None, **_kwargs):
        try:
            return self.value_at(image_index(p, index, all_prompts))
        except Exception:
            return None

    def __eq__(self, other):
        return isinstance(other, ImageInfotext) and (self.values, self.fmt) == (other.values, other.fmt)

    __hash__ = None

    def __repr__(self):
        return f"ImageInfotext({self.values!r})"


def prompt_lists(p):
    """The four prompt lists of `p` as tuples (None for a missing / non-list attribute), compared by
    value: ADetailer's preserve_prompts() puts equal COPIES of the lists back on `p`."""
    result = []
    for attr in _PROMPT_LISTS:
        v = getattr(p, attr, None)
        result.append(tuple(v) if isinstance(v, (list, tuple)) else None)
    return tuple(result)


def already_processed(p):
    """True when `p` (or the object it was copied from) went through process() and its prompt lists are
    still the ones process() left: a second call must do nothing (design notes 33 A)."""
    marker = getattr(p, DONE_ATTR, None)
    return marker is not None and marker == prompt_lists(p)


def mark_processed(p):
    setattr(p, DONE_ATTR, prompt_lists(p))


def expand_list(prompts, rng_seeds, blocks, lora=True, ban_events=None):
    # lora=False for negative prompts (design notes section 13): no block LoRA is inserted there.
    # Each prompt has its own ban set (section 38). `ban_events`: if a list, one events list per prompt.
    result = []
    for pr, sd in zip(prompts, rng_seeds):
        ev = [] if ban_events is not None else None
        result.append(parser.expand(pr, blocks, random.Random(sd), lora=lora, ban_events=ev))
        if ban_events is not None:
            ban_events.append(ev)
    return result


def ban_console_lines(pos_events, neg_events):
    """Debug console lines (section 38): one per image whose positive or negative prompt had a ban effect,
    e.g. "bans image 0: ninja: ~happy kept out of %PEmotion | negative: ...". ASCII only."""
    lines = []
    for i in range(max(len(pos_events), len(neg_events))):
        pos = bans.console_line(pos_events[i]) if i < len(pos_events) else ""
        neg = bans.console_line(neg_events[i]) if i < len(neg_events) else ""
        if not pos and not neg:
            continue
        parts = ([pos] if pos else []) + (["negative: " + neg] if neg else [])
        line = f"bans image {i}: " + " | ".join(parts)
        lines.append(line.encode("ascii", "backslashreplace").decode("ascii"))
    return lines


def store_adetailer_additions(p, enabled, blocks, img_uses, img_seeds, hook_ready, log=print, debug=_noop):
    """Section 31a: hook ADetailer (hook_ready() installs it and says whether an instance is hooked) and
    store the additions per image and tab on p. Nothing is stored when the checkbox is off or no ADetailer
    instance could be hooked. Returns the stored table (None = nothing). Never raises: generation must not
    break because of this."""
    try:
        setattr(p, adetailer.P_ATTR, None)
        setattr(p, adetailer.APPLIED_ATTR, None)
        if not enabled or not hook_ready():
            return None
        errors = []
        table = adetailer.all_additions(blocks, img_uses, img_seeds, errors)
        if errors:
            log("[PromptBlocks] ADetailer text skipped: " + errors[0]
                + (f" (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
        setattr(p, adetailer.P_ATTR, table)
        # Design notes 34 B: the hook records here what it really appended (job-wide image index ->
        # per tab [(name, text)]); the infotext key reads only these records.
        setattr(p, adetailer.APPLIED_ATTR, {} if table else None)
        debug("adetailer      =", table)
        return table
    except Exception as e:
        log(f"[PromptBlocks] ADetailer text not added: {type(e).__name__}: {e}")
        return None


def _lora_sync_value(changed):
    return adetailer.LORA_SYNC_VALUE if changed else None


def setup_lora_sync(p, enabled, hook_ready, log=print, debug=_noop):
    """Design notes 35: when "Keep main LoRAs in ADetailer" is on and hook_ready() hooked an ADetailer
    instance, put a fresh adetailer.LoraSync on `p` (its infotext value is an ImageInfotext over the
    per-image change record; the hook adds the key on the first change). Independent of blocks and of
    the section 31a additions. Returns the LoraSync or None. Never raises."""
    try:
        setattr(p, adetailer.LORA_SYNC_ATTR, None)
        if not enabled or not hook_ready():
            return None
        sync = adetailer.LoraSync()
        sync.infotext = ImageInfotext(sync.changed, _lora_sync_value)
        setattr(p, adetailer.LORA_SYNC_ATTR, sync)
        debug("adetailer lora = sync on")
        return sync
    except Exception as e:
        log(f"[PromptBlocks] ADetailer LoRA sync not set up: {type(e).__name__}: {e}")
        return None


def _once(fn):
    # hook_ready() is needed by the LoRA sync and the additions; install it only once per process().
    done = []

    def wrapper():
        if not done:
            done.append(fn())
        return done[0]
    return wrapper


def process(p, tab, args, load_blocks, hook_ready, log=print, debug=_noop):
    """Expand all prompt lists of `p` (see CLAUDE.md "Architecture"). `args` = the Script args
    (block seed, add ADetailer text). `load_blocks()` returns the blocks dict; `hook_ready()` installs
    the ADetailer hook and returns whether it is active."""
    if already_processed(p):
        debug("process        = skipped (prompts already expanded by PromptBlocks)")
        return
    state.last_picks[tab] = []
    # Design notes 34 C: a run on the same p (Loopback, SD upscale) starts without the previous run's
    # values; each key below is written again only when this run produces it.
    for key in (ADETAILER_INFOTEXT_KEY, PICKS_INFOTEXT_KEY, TEMPLATE_INFOTEXT_KEY, SEED_INFOTEXT_KEY,
                LORA_SYNC_INFOTEXT_KEY):
        p.extra_generation_params.pop(key, None)
    for attr in (adetailer.P_ATTR, adetailer.APPLIED_ATTR, adetailer.LORA_SYNC_ATTR):
        if getattr(p, attr, None) is not None:
            setattr(p, attr, None)

    block_seed = args[0] if args else -1
    add_adetailer = bool(args[1]) if len(args) > 1 else True
    keep_loras = bool(args[2]) if len(args) > 2 else True
    hook_ready = _once(hook_ready)
    # Design notes 35: the LoRA sync is a general guard, set up before (and independent of) the blocks.
    setup_lora_sync(p, keep_loras, hook_ready, log, debug)

    blocks = load_blocks()
    # A Generate with blocks loaded counts even if it picks nothing random (design notes 23b).
    state.last_generated[tab] = bool(blocks)
    if not blocks:
        # Marked too: ADetailer's re-run on copy(p) shares extra_generation_params and must not remove
        # the LoRA sync key (section 33 A guard).
        mark_processed(p)
        return

    base_seed, img_seeds = seeds.block_seeds(block_seed, len(p.all_prompts))
    debug("block seed     =", block_seed, "-> base", base_seed)

    original = p.prompt
    try:
        # Positive list also records the depth-0 picks and the sub-block trace per image (section 15)
        # and the block uses per image (section 31a, ADetailer texts).
        # Section 38: bans apply in every list (each prompt its own ban set); the effects of the main
        # positive / negative lists go to the debug console only (no infotext key).
        img_uses, pos_bans, neg_bans = [], [], []
        new_pos, img_picks, img_traces = picks.expand_recorded(p.all_prompts, img_seeds, blocks,
                                                               uses=img_uses, ban_events=pos_bans)
        new_neg = expand_list(p.all_negative_prompts, img_seeds, blocks, lora=False, ban_events=neg_bans)
        hr_pos = getattr(p, "all_hr_prompts", None)
        hr_neg = getattr(p, "all_hr_negative_prompts", None)
        new_hr_pos = expand_list(hr_pos, img_seeds, blocks) if hr_pos else None
        new_hr_neg = expand_list(hr_neg, img_seeds, blocks, lora=False) if hr_neg else None
    except parser.BlockCycleError as e:
        log(f"[PromptBlocks] ERROR: {e} - prompts left unchanged")
        mark_processed(p)  # see the "not blocks" case above
        return

    for line in ban_console_lines(pos_bans, neg_bans):
        debug(line)

    table = store_adetailer_additions(p, add_adetailer, blocks, img_uses, img_seeds, hook_ready, log, debug)
    # Sections 33 F / 34 B: what the hook really appended to ADetailer's prompts, per image (information
    # only, not pasted). Images the hook did not touch (ADetailer Enable off, tab off) get no key.
    applied = getattr(p, adetailer.APPLIED_ATTR, None)
    if table and isinstance(applied, dict):
        p.extra_generation_params[ADETAILER_INFOTEXT_KEY] = ImageInfotext(applied, adetailer.infotext_summary)

    state.last_picks[tab] = img_picks[0] if img_picks else []
    summaries = [picks.summary(pk, tr) for pk, tr in zip(img_picks, img_traces)]
    if any(summaries):
        # One summary per image (job-wide index, design notes 34 A); None -> key omitted for that image.
        p.extra_generation_params[PICKS_INFOTEXT_KEY] = ImageInfotext([s or None for s in summaries])

    changed = new_pos != p.all_prompts or new_neg != p.all_negative_prompts

    p.all_prompts = new_pos
    p.all_negative_prompts = new_neg
    if new_hr_pos is not None:
        p.all_hr_prompts = new_hr_pos
    if new_hr_neg is not None:
        p.all_hr_negative_prompts = new_hr_neg
    mark_processed(p)

    if changed:
        p.extra_generation_params[TEMPLATE_INFOTEXT_KEY] = original
        p.extra_generation_params[SEED_INFOTEXT_KEY] = base_seed

    debug("changed        =", changed)
    debug("all_prompts    =", p.all_prompts)
    debug("all_hr_prompts =", getattr(p, "all_hr_prompts", None))
    debug("all_negative_prompts =", p.all_negative_prompts)
