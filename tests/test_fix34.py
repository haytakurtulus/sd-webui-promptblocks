"""Per-image infotext correct for Batch count > 1 (design notes section 34): A job-wide index mapping and
the ImageInfotext callable, B the ADetailer key from what the hook really appended, C no stale keys after
a second run on the same p (Loopback)."""

import copy
import json
import re

import pytest

from pb_core import adetailer, generate, state

BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber", "adetailer": ["blonde hair", "blue eyes", "", ""]},
    "rin": {"category": "PChar", "text": "1girl, rin", "adetailer": ["black hair", "", "", ""]},
    "plain": {"category": "PChar", "text": "1boy"},
    "happy": {"category": "PEmo", "text": "smile"},
    "sad": {"category": "PEmo", "text": "tears"},
    "angry": {"category": "PEmo", "text": "frown"},
}

KEYS = (generate.PICKS_INFOTEXT_KEY, generate.TEMPLATE_INFOTEXT_KEY, generate.SEED_INFOTEXT_KEY,
        generate.ADETAILER_INFOTEXT_KEY)


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})
    monkeypatch.setattr(state, "last_generated", {"txt2img": False, "img2img": False})


class FakeP:
    """A StableDiffusionProcessing stand-in with Batch count (n_iter) and Batch size."""

    def __init__(self, prompt, n_iter=2, batch_size=2, negative=""):
        self.prompt = prompt
        self.negative_prompt = negative
        self.n_iter = n_iter
        self.batch_size = batch_size
        self.iteration = 0
        self.batch_index = 0
        self.extra_generation_params = {}
        self.setup_prompts()

    def setup_prompts(self):
        n = self.n_iter * self.batch_size
        self.all_prompts = [self.prompt] * n
        self.all_negative_prompts = [self.negative_prompt] * n

    def batch(self, it):
        # Like process_images_inner(): p.iteration and the batch slice p.prompts.
        self.iteration = it
        self.prompts = self.all_prompts[it * self.batch_size:(it + 1) * self.batch_size]
        return self.prompts


def run(p, blocks=BLOCKS, seed=7, add_ad=True, hook=True, log=None):
    generate.process(p, "txt2img", (seed, add_ad), lambda: blocks,
                     hook_ready=lambda: hook, log=log or (lambda *a: None))


def forge_value(p, key, all_prompts, index):
    """How Forge's create_infotext() resolves one extra_generation_params value (modules/processing.py):
    list -> value[index]; callable -> value(**locals()); an exception -> None."""
    value = p.extra_generation_params.get(key)
    use_main_prompt = False  # noqa: F841 - part of locals() like in Forge
    all_seeds = [1] * len(all_prompts)  # noqa: F841
    try:
        if isinstance(value, list):
            return value[index]
        if callable(value):
            return value(**locals())
        return value
    except Exception:
        return None


# ---------------------------------------------------------------- A: index mapping

def test_image_index_batch_slice_and_full_list():
    p = FakeP("x", n_iter=2, batch_size=2)
    sl = p.batch(1)
    assert generate.image_index(p, 1, sl) == 3          # infotext(i): in-batch index, batch slice
    assert generate.image_index(p, 3, p.all_prompts) == 3  # Processed.infotext: global index, full list
    assert generate.image_index(p, 0, sl) == 2
    sl = p.batch(0)
    assert generate.image_index(p, 1, sl) == 1


def test_image_index_batch_count_1_unchanged():
    p = FakeP("x", n_iter=1, batch_size=3)
    sl = p.batch(0)
    for i in range(3):
        assert generate.image_index(p, i, sl) == i
        assert generate.image_index(p, i, p.all_prompts) == i
    p = FakeP("x", n_iter=3, batch_size=1)
    assert generate.image_index(p, 0, p.batch(2)) == 2


def test_picks_key_gives_image_3_value_both_ways():
    p = FakeP("%PEmo", n_iter=2, batch_size=2)
    run(p, seed=3)
    fn = p.extra_generation_params[generate.PICKS_INFOTEXT_KEY]
    assert isinstance(fn, generate.ImageInfotext) and not isinstance(fn, list)
    values = fn.values
    assert len(values) == 4 and all(values)
    for k in range(4):  # each value names this image's own pick
        emo = {"smile": "happy", "tears": "sad", "frown": "angry"}[p.all_prompts[k]]
        assert emo in values[k]
    sl = p.batch(1)
    assert forge_value(p, generate.PICKS_INFOTEXT_KEY, sl, 1) == values[3]
    assert forge_value(p, generate.PICKS_INFOTEXT_KEY, p.all_prompts, 3) == values[3]
    assert forge_value(p, generate.PICKS_INFOTEXT_KEY, sl, 0) == values[2]
    # The old list behaviour would have given image 1's value for the first call.
    sl = p.batch(0)
    assert [forge_value(p, generate.PICKS_INFOTEXT_KEY, sl, i) for i in range(2)] == values[:2]


def test_picks_key_batch_count_1_unchanged():
    p = FakeP("%PEmo", n_iter=1, batch_size=3)
    run(p, seed=5)
    fn = p.extra_generation_params[generate.PICKS_INFOTEXT_KEY]
    sl = p.batch(0)
    for i in range(3):
        assert forge_value(p, generate.PICKS_INFOTEXT_KEY, sl, i) == fn.values[i]
        assert forge_value(p, generate.PICKS_INFOTEXT_KEY, p.all_prompts, i) == fn.values[i]


def test_callable_is_json_safe_like_processed_js():
    p = FakeP("%PEmo", n_iter=1, batch_size=1)
    run(p)
    # Processed.js(): json.dumps(obj, default=lambda o: None)
    out = json.loads(json.dumps(p.extra_generation_params, default=lambda o: None))
    assert out[generate.PICKS_INFOTEXT_KEY] is None


# ---------------------------------------------------------------- A: out of range / broken -> None

class Broken:
    pass


@pytest.mark.parametrize("index, all_prompts", [(4, "full"), (-1, "full"), (2, "slice"), (-3, "slice"),
                                                ("1", "full"), (True, "full"), (None, "full"),
                                                (0, None), (1.0, "full")])
def test_out_of_range_or_bad_index_gives_none(index, all_prompts):
    p = FakeP("x", n_iter=2, batch_size=2)
    sl = p.batch(1)
    lists = {"full": p.all_prompts, "slice": sl, None: None}
    fn = generate.ImageInfotext(["a", "b", "c", "d"])
    assert fn(p=p, index=index, all_prompts=lists[all_prompts]) is None


def test_broken_p_gives_none():
    fn = generate.ImageInfotext(["a", "b"])
    assert fn(p=Broken(), index=0, all_prompts=["x"]) is None
    assert fn(p=None, index=0, all_prompts=["x"]) is None
    assert fn() is None
    p = FakeP("x", n_iter=2, batch_size=1)
    p.iteration = None
    assert fn(p=p, index=0, all_prompts=["x"]) is None
    p.iteration, p.batch_size = 0, "2"
    assert fn(p=p, index=0, all_prompts=["x"]) is None
    p = FakeP("x", n_iter=1, batch_size=2)
    p.all_prompts = None
    assert fn(p=p, index=0, all_prompts=["x"]) is None


def test_values_shorter_than_job_or_bad_fmt_gives_none():
    p = FakeP("x", n_iter=1, batch_size=3)
    assert generate.ImageInfotext(["a"])(p=p, index=2, all_prompts=p.all_prompts) is None
    assert generate.ImageInfotext([""])(p=p, index=0, all_prompts=p.all_prompts) is None

    def boom(_v):
        raise ValueError("x")

    assert generate.ImageInfotext({0: 1}, boom)(p=p, index=0, all_prompts=p.all_prompts) is None
    assert generate.ImageInfotext({})(p=p, index=0, all_prompts=p.all_prompts) is None
    assert generate.ImageInfotext(None)(p=p, index=0, all_prompts=p.all_prompts) is None


# ---------------------------------------------------------------- B: ADetailer key = what was applied

class FakeArgs:
    def __init__(self, ad_prompt=""):
        self.ad_prompt = ad_prompt
        self.ad_negative_prompt = ""


class FakeADetailer:
    """The parts of ADetailer the hook relies on (scripts/!adetailer.py): postprocess_image runs with the
    main p, loops the tabs with _postprocess_image_inner(p, pp, args, n=n), which calls get_prompt(p, args);
    nothing at all when ADetailer's own Enable is off."""

    def __init__(self):
        self.seen = []

    def title(self):
        return "ADetailer"

    def get_prompt(self, p, args):
        i = p.iteration * p.batch_size + p.batch_index
        parts = re.split(r"\s*\[SEP\]\s*", args.ad_prompt)
        return [p.all_prompts[i] if not x else x for x in parts], [args.ad_negative_prompt]

    def _postprocess_image_inner(self, p, pp, args, *, n=0):
        self.seen.append((n, self.get_prompt(p, args)[0]))
        return True

    def postprocess_image(self, p, pp, enabled, *arg_list):
        if not enabled:
            return
        for n, args in enumerate(arg_list):
            if args is None:  # tab off (need_skip)
                continue
            self._postprocess_image_inner(p, pp, args, n=n)


def generate_with_adetailer(p, ad, per_image):
    """Forge's loop: per batch and image set iteration / batch_index, run postprocess_image (ADetailer)
    with `per_image(global index)` -> (enabled, *tab args), then read the PNG text value infotext(i)."""
    texts = []
    for it in range(p.n_iter):
        sl = p.batch(it)
        for i in range(p.batch_size):
            p.batch_index = i
            g = it * p.batch_size + i
            ad.postprocess_image(p, None, *per_image(g))
            texts.append(forge_value(p, generate.ADETAILER_INFOTEXT_KEY, sl, i))
    return texts


def test_adetailer_key_only_for_images_the_hook_appended_to():
    ad = FakeADetailer()
    assert adetailer.install(ad, print)
    p = FakeP("~saber", n_iter=2, batch_size=2)
    run(p)
    # Image 1: Enable off; image 2: only tab 2; images 0, 3: tabs 1 and 2.
    plan = {0: (True, FakeArgs(), FakeArgs()), 1: (False, FakeArgs(), FakeArgs()),
            2: (True, None, FakeArgs()), 3: (True, FakeArgs(), FakeArgs())}
    texts = generate_with_adetailer(p, ad, plan.__getitem__)
    assert texts == ["1st: blonde hair; 2nd: blue eyes", None, "2nd: blue eyes",
                     "1st: blonde hair; 2nd: blue eyes"]
    # The same values through Processed.infotext (global index, full list).
    assert [forge_value(p, generate.ADETAILER_INFOTEXT_KEY, p.all_prompts, g) for g in range(4)] == texts


def test_adetailer_key_differs_per_batch():
    ad = FakeADetailer()
    adetailer.install(ad, print)
    p = FakeP("%PChar", n_iter=2, batch_size=1)
    p.all_prompts = ["~saber", "~rin"]
    run(p)
    texts = generate_with_adetailer(p, ad, lambda g: (True, FakeArgs()))
    assert texts == ["1st: blonde hair", "1st: black hair"]


def test_adetailer_enable_off_gives_no_key_value():
    ad = FakeADetailer()
    adetailer.install(ad, print)
    p = FakeP("~saber", n_iter=1, batch_size=2)
    run(p)
    assert generate_with_adetailer(p, ad, lambda g: (False, FakeArgs())) == [None, None]
    # A block without ADetailer text: nothing appended, no record.
    p = FakeP("~plain", n_iter=1, batch_size=1)
    run(p)
    assert generate_with_adetailer(p, ad, lambda g: (True, FakeArgs())) == [None]


def test_adetailer_key_absent_when_checkbox_off_or_no_hook():
    for add_ad, hook in ((False, True), (True, False)):
        ad = FakeADetailer()
        adetailer.install(ad, print)
        p = FakeP("~saber", n_iter=1, batch_size=1)
        run(p, add_ad=add_ad, hook=hook)
        assert generate.ADETAILER_INFOTEXT_KEY not in p.extra_generation_params
        generate_with_adetailer(p, ad, lambda g: (True, FakeArgs()))
        assert ad.seen == [(0, ["1girl, saber"])]  # nothing appended
        assert getattr(p, adetailer.APPLIED_ATTR, None) is None


def test_record_applied_without_record_dict_does_nothing():
    p = FakeP("x", n_iter=1, batch_size=1)
    adetailer.record_applied(p, 0, [("a", "A")])
    assert getattr(p, adetailer.APPLIED_ATTR, None) is None
    setattr(p, adetailer.APPLIED_ATTR, {})
    adetailer.record_applied(p, 7, [("a", "A")])  # tab outside 1..4
    assert getattr(p, adetailer.APPLIED_ATTR) == {}
    adetailer.record_applied(p, 1, [("a", "A")])
    assert getattr(p, adetailer.APPLIED_ATTR) == {0: [[], [("a", "A")], [], []]}


# ---------------------------------------------------------------- C: no stale keys on the same p

def test_loopback_rerun_without_picks_removes_picks_key():
    p = FakeP("%PEmo", n_iter=1, batch_size=1)
    run(p)
    assert all(k in p.extra_generation_params for k in KEYS[:3])
    p.prompt = "~rin"  # Loopback-like: same p, a template that picks nothing random
    p.setup_prompts()
    run(p)
    assert generate.PICKS_INFOTEXT_KEY not in p.extra_generation_params
    assert p.extra_generation_params[generate.TEMPLATE_INFOTEXT_KEY] == "~rin"


def test_loopback_rerun_without_change_removes_all_stale_keys():
    ad = FakeADetailer()
    adetailer.install(ad, print)
    p = FakeP("~saber, %PEmo", n_iter=1, batch_size=1)
    run(p)
    generate_with_adetailer(p, ad, lambda g: (True, FakeArgs()))
    assert all(k in p.extra_generation_params for k in KEYS)
    p.prompt = "plain text"
    p.setup_prompts()
    run(p)
    for k in KEYS:
        assert k not in p.extra_generation_params
    assert getattr(p, adetailer.P_ATTR) is None and getattr(p, adetailer.APPLIED_ATTR) is None
    assert p.all_prompts == ["plain text"]


def test_rerun_with_cycle_error_or_no_blocks_leaves_no_stale_keys():
    p = FakeP("%PEmo", n_iter=1, batch_size=1)
    run(p)
    cyc = {"a": {"category": "C", "text": "~b"}, "b": {"category": "C", "text": "~a"}}
    p.prompt = "~a"
    p.setup_prompts()
    run(p, blocks=cyc)
    assert not any(k in p.extra_generation_params for k in KEYS)
    p.prompt = "%PEmo"
    p.setup_prompts()
    run(p)
    p.setup_prompts()
    run(p, blocks={})
    assert not any(k in p.extra_generation_params for k in KEYS)


def test_rerun_guard_on_copy_keeps_keys():
    # Section 33 A unchanged: ADetailer's process() on copy(p) leaves everything alone.
    p = FakeP("%PEmo", n_iter=1, batch_size=1)
    run(p)
    before = copy.deepcopy(p.extra_generation_params)
    p.all_prompts = list(p.all_prompts)
    run(copy.copy(p), seed=99)
    assert p.extra_generation_params == before and generate.PICKS_INFOTEXT_KEY in before
