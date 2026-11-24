"""Design notes section 35 "Keep main LoRAs in ADetailer": the pure helpers (lora_tags_in_order,
strip_lora_tags, sync_loras, lora_source, uses_own_checkpoint), the hook step and generate.process()
(flag on p independent of blocks, infotext key only when something changed, checkbox off = today)."""

import copy
import re

import pytest

from pb_core import adetailer, generate, lora, state


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})
    monkeypatch.setattr(state, "last_generated", {"txt2img": False, "img2img": False})


# ---------------------------------------------------------------- fakes

class FakeArgs:
    def __init__(self, ad_prompt="", use_ckpt=False, ckpt="Use same checkpoint"):
        self.ad_prompt = ad_prompt
        self.ad_negative_prompt = "neg, <lora:N:1>"
        self.ad_use_checkpoint = use_ckpt
        self.ad_checkpoint = ckpt


class FakeADetailer:
    """ADetailer's get_prompt (split on [SEP], empty part / [PROMPT] -> all_prompts[i]) and the tab loop."""

    def __init__(self):
        self.seen = []

    def title(self):
        return "ADetailer"

    def get_prompt(self, p, args):
        i = p.iteration * p.batch_size + p.batch_index
        parts = re.split(r"\s*\[SEP\]\s*", args.ad_prompt)
        parts = [p.all_prompts[i] if not x else x.replace("[PROMPT]", p.all_prompts[i]) for x in parts]
        return parts, [args.ad_negative_prompt]

    def _postprocess_image_inner(self, p, pp, args, *, n=0):
        self.seen.append((n, self.get_prompt(p, args)))
        return True

    def postprocess_image(self, p, pp, *arg_list):
        for n, args in enumerate(arg_list):
            self._postprocess_image_inner(p, pp, args, n=n)


class FakeP:
    def __init__(self, prompt, n_iter=1, batch_size=1, hr=False):
        self.prompt = prompt
        self.negative_prompt = ""
        self.n_iter = n_iter
        self.batch_size = batch_size
        self.iteration = 0
        self.batch_index = 0
        self.enable_hr = hr
        self.extra_generation_params = {}
        self.setup_prompts()

    def setup_prompts(self):
        n = self.n_iter * self.batch_size
        self.all_prompts = [self.prompt] * n
        self.all_negative_prompts = [self.negative_prompt] * n
        if self.enable_hr:
            self.all_hr_prompts = [self.prompt] * n
            self.all_hr_negative_prompts = [self.negative_prompt] * n


def run(p, blocks, args, hook=True, log=None):
    calls = []
    generate.process(p, "txt2img", args, lambda: blocks,
                     hook_ready=lambda: calls.append(1) or hook, log=log or (lambda *a: None))
    return calls


def forge_value(p, key, index, all_prompts=None):
    value = p.extra_generation_params.get(key)
    if value is None:
        return None
    return value(p=p, index=index, all_prompts=p.all_prompts if all_prompts is None else all_prompts)


def hooked():
    ad = FakeADetailer()
    assert adetailer.install(ad, print)
    return ad


# ---------------------------------------------------------------- lora helpers

def test_lora_tags_in_order_keeps_duplicates_and_spelling():
    text = "a, <lora:R:1>, b <LORA:r:1.0>, <lora:R:1>, <lyco:L:0.5>"
    assert lora.lora_tags_in_order(text) == ["<lora:R:1>", "<LORA:r:1.0>", "<lora:R:1>", "<lyco:L:0.5>"]
    assert lora.lora_tags_in_order("no tags") == []
    assert lora.lora_tags_in_order(None) == []


def test_strip_lora_tags_keeps_rest():
    assert lora.strip_lora_tags("a, <lora:X:1>, b") == "a, b"
    assert lora.strip_lora_tags("<lora:X:1>, a, <lora:Y:1>") == "a"
    assert lora.strip_lora_tags("plain (text:1.2)") == "plain (text:1.2)"
    assert lora.strip_lora_tags(None) == ""


# ---------------------------------------------------------------- acceptance 1-3: sync_loras

def test_acceptance_1_replace_and_append_in_source_order():
    assert adetailer.sync_loras(["a, <lora:X:1>, b"], "q, <lora:R:0.8>, w, <lora:S:0.6>") == \
        ["a, b, <lora:R:0.8>, <lora:S:0.6>"]


def test_acceptance_2_duplicates_and_odd_spellings_verbatim():
    src = "x, <lora:R:1>, <LORA:r:1.0>, <lora:R:1>"
    assert adetailer.sync_loras(["face, <lora:F:1>"], src) == \
        ["face, <lora:R:1>, <LORA:r:1.0>, <lora:R:1>"]


def test_acceptance_3_skip_part_and_empty_source():
    src = "q, <lora:R:0.8>"
    assert adetailer.sync_loras(["[SKIP]", " [SKIP] ", "b"], src) == ["[SKIP]", " [SKIP] ", "b, <lora:R:0.8>"]
    assert adetailer.sync_loras(["a, <lora:X:1>, b", "<lora:Y:1>"], "no loras here") == ["a, b", ""]


def test_sync_part_already_matching_is_unchanged():
    # The usual empty ADetailer prompt: the part IS the main prompt, nothing may move.
    main = "a, <lora:R:0.8>, b, <lora:S:0.6>"
    parts = [main, "x <lora:R:0.8> y <lora:S:0.6>"]
    assert adetailer.sync_loras(parts, main) == parts
    # Same tags in another order are a different load list -> synced.
    assert adetailer.sync_loras(["<lora:S:0.6>, f, <lora:R:0.8>"], main) == ["f, <lora:R:0.8>, <lora:S:0.6>"]


def test_sync_joining_rules():
    src = "<lora:R:1>"
    assert adetailer.sync_loras(["face,"], src) == ["face, <lora:R:1>"]
    assert adetailer.sync_loras([""], src) == ["<lora:R:1>"]
    assert adetailer.sync_loras(["line1\nline2"], src) == ["line1\nline2, <lora:R:1>"]
    parts = ["a"]
    assert adetailer.sync_loras(parts, src) is not parts


def test_uses_own_checkpoint():
    assert not adetailer.uses_own_checkpoint(FakeArgs())
    assert not adetailer.uses_own_checkpoint(FakeArgs(use_ckpt=True))
    for same in (None, "", "None", "Use same checkpoint"):
        assert not adetailer.uses_own_checkpoint(FakeArgs(use_ckpt=True, ckpt=same))
    assert adetailer.uses_own_checkpoint(FakeArgs(use_ckpt=True, ckpt="other.safetensors"))
    assert not adetailer.uses_own_checkpoint(FakeArgs(use_ckpt=False, ckpt="other.safetensors"))
    assert not adetailer.uses_own_checkpoint(None)


# ---------------------------------------------------------------- acceptance 4: lora_source

def test_acceptance_4_source_index_and_hires():
    p = FakeP("x", n_iter=2, batch_size=2)
    p.all_prompts = [f"p{i}" for i in range(4)]
    p.iteration, p.batch_index = 1, 1
    assert adetailer.lora_source(p) == "p2"
    p.enable_hr = True
    p.all_hr_prompts = [f"hr{i}" for i in range(4)]
    assert adetailer.lora_source(p) == "hr2"
    p.all_hr_prompts = []  # hires on but no list -> main list
    assert adetailer.lora_source(p) == "p2"
    p.enable_hr = False
    p.all_hr_prompts = [f"hr{i}" for i in range(4)]
    assert adetailer.lora_source(p) == "p2"


def test_lora_source_missing_or_out_of_range():
    p = FakeP("x", n_iter=1, batch_size=2)
    p.iteration = 1
    assert adetailer.lora_source(p) is None
    p.iteration = "1"
    assert adetailer.lora_source(p) is None
    assert adetailer.lora_source(object()) is None


# ---------------------------------------------------------------- hook + process

BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber", "lora": "<lora:Saber:0.8>",
              "adetailer": ["blonde hair, <lora:FaceS:1>", "", "", ""]},
    "plain": {"category": "PChar", "text": "1boy"},
}


def test_acceptance_5_hand_tab_without_additions_is_synced():
    ad = hooked()
    p = FakeP("~saber, <lora:Main:0.5>")
    run(p, BLOCKS, (7, True, True))
    assert p.all_prompts == ["1girl, saber, <lora:Saber:0.8>, <lora:Main:0.5>"]
    ad.postprocess_image(p, None, FakeArgs("face"), FakeArgs("hand, <lora:Hand:1>"))
    (n0, (parts0, neg0)), (n1, (parts1, neg1)) = ad.seen
    # Tab 1: block addition appended (its own LoRA replaced too); tab 2 (hand, no addition) synced.
    assert parts0 == ["face, blonde hair, <lora:Saber:0.8>, <lora:Main:0.5>"]
    assert parts1 == ["hand, <lora:Saber:0.8>, <lora:Main:0.5>"]
    assert neg0 == neg1 == ["neg, <lora:N:1>"]  # negatives untouched
    # record_applied only for the tab with block additions.
    assert getattr(p, adetailer.APPLIED_ATTR) == {0: [[("saber", "blonde hair, <lora:FaceS:1>")], [], [], []]}


@pytest.mark.parametrize("blocks", [{}, BLOCKS])
def test_acceptance_5_prompt_without_blocks_is_synced(blocks):
    ad = hooked()
    p = FakeP("plain prompt, <lora:Main:1>")
    calls = run(p, blocks, (-1, True, True))
    assert calls == [1]  # hook installed although no block is used / loaded
    ad.postprocess_image(p, None, FakeArgs("face, <lora:Face:1>"))
    assert ad.seen[0][1][0] == ["face, <lora:Main:1>"]
    assert forge_value(p, generate.LORA_SYNC_INFOTEXT_KEY, 0) == "on"


def test_hook_installed_and_synced_after_cycle_error():
    ad = hooked()
    blocks = {"a": {"category": "C", "text": "~b"}, "b": {"category": "C", "text": "~a"}}
    p = FakeP("~a, <lora:Main:1>")
    logs = []
    calls = run(p, blocks, (-1, True, True), log=logs.append)
    assert calls == [1] and "ERROR" in logs[0]
    ad.postprocess_image(p, None, FakeArgs("face, <lora:Face:1>"))
    assert ad.seen[0][1][0] == ["face, <lora:Main:1>"]


def test_acceptance_3_separate_checkpoint_tab_and_skip_unchanged():
    ad = hooked()
    p = FakeP("main, <lora:Main:1>")
    run(p, {}, (-1, True, True))
    ad.postprocess_image(p, None, FakeArgs("face, <lora:Face:1>", use_ckpt=True, ckpt="other.safetensors"),
                         FakeArgs("[SKIP] [SEP] f2, <lora:Face:1>"))
    assert ad.seen[0][1][0] == ["face, <lora:Face:1>"]
    assert ad.seen[1][1][0] == ["[SKIP]", "f2, <lora:Main:1>"]


def test_hires_source_used_by_hook():
    ad = hooked()
    p = FakeP("main, <lora:Main:1>", hr=True)
    p.all_hr_prompts = ["hires, <lora:Hr:1>"]
    run(p, {}, (-1, True, True))
    ad.postprocess_image(p, None, FakeArgs("face"))
    assert ad.seen[0][1][0] == ["face, <lora:Hr:1>"]


def test_empty_adetailer_prompt_with_batch_uses_batch_first_prompt():
    ad = hooked()
    p = FakeP("x", n_iter=1, batch_size=2)
    p.all_prompts = ["a, <lora:A:1>", "b, <lora:B:1>"]
    run(p, {}, (-1, True, True))
    p.batch_index = 1
    ad.postprocess_image(p, None, FakeArgs(""))
    assert ad.seen[0][1][0] == ["b, <lora:A:1>"]
    # Image 1 changed, image 0 has no record.
    assert forge_value(p, generate.LORA_SYNC_INFOTEXT_KEY, 1) == "on"
    assert forge_value(p, generate.LORA_SYNC_INFOTEXT_KEY, 0) is None


@pytest.mark.parametrize("add_ad", [True, False])
@pytest.mark.parametrize("prompt", ["~saber, <lora:Main:0.5>", "plain, <lora:Main:1>"])
def test_acceptance_6_checkbox_off_is_today(add_ad, prompt):
    ad_prompts = ["face, <lora:Face:1>", "", "[SKIP] [SEP] x <lora:Q:1>"]
    ad = hooked()
    p = FakeP(prompt)
    run(p, BLOCKS, (7, add_ad, False))
    ad.postprocess_image(p, None, *[FakeArgs(x) for x in ad_prompts])
    # Today (before section 35): ADetailer's own parts, plus assign() of the block additions only.
    raw = FakeADetailer()
    raw.postprocess_image(p, None, *[FakeArgs(x) for x in ad_prompts])
    expected = []
    for n, (parts, negs) in raw.seen:
        adds = adetailer.additions_for(p, n)
        expected.append((n, (adetailer.assign(parts, adds) if adds else parts, negs)))
    assert ad.seen == expected
    if add_ad and prompt.startswith("~saber"):
        assert ad.seen[0][1][0] == ["face, <lora:Face:1>, blonde hair, <lora:FaceS:1>"]
    else:
        assert ad.seen == raw.seen
    assert generate.LORA_SYNC_INFOTEXT_KEY not in p.extra_generation_params
    assert getattr(p, adetailer.LORA_SYNC_ATTR) is None


def test_missing_third_arg_defaults_on():
    ad = hooked()
    p = FakeP("m, <lora:Main:1>")
    run(p, {}, (-1, True))
    ad.postprocess_image(p, None, FakeArgs("face"))
    assert ad.seen[0][1][0] == ["face, <lora:Main:1>"]
    p2 = FakeP("m, <lora:Main:1>")
    run(p2, {}, ())
    assert isinstance(getattr(p2, adetailer.LORA_SYNC_ATTR), adetailer.LoraSync)


def test_no_hook_no_sync():
    p = FakeP("m, <lora:Main:1>")
    run(p, {}, (-1, True, True), hook=False)
    assert getattr(p, adetailer.LORA_SYNC_ATTR) is None


def test_acceptance_7_key_only_when_something_changed():
    ad = hooked()
    p = FakeP("m, <lora:Main:1>")
    run(p, {}, (-1, True, True))
    ad.postprocess_image(p, None, FakeArgs(""), FakeArgs("face, <lora:Main:1>"))  # nothing to change
    assert generate.LORA_SYNC_INFOTEXT_KEY not in p.extra_generation_params
    ad.postprocess_image(p, None, FakeArgs("face, <lora:Other:1>"))
    assert forge_value(p, generate.LORA_SYNC_INFOTEXT_KEY, 0) == "on"


def test_key_per_image_with_batch_count():
    ad = hooked()
    p = FakeP("x", n_iter=2, batch_size=1)
    p.all_prompts = ["a, <lora:A:1>", "b"]
    run(p, {}, (-1, True, True))
    for it in range(2):
        p.iteration = it
        ad.postprocess_image(p, None, FakeArgs("face, <lora:A:1>"))
    # Image 0 already had the same tags; image 1's source has none -> tag removed.
    assert ad.seen[1][1][0] == ["face"]
    batch1 = p.all_prompts[1:2]
    p.iteration = 1
    assert forge_value(p, generate.LORA_SYNC_INFOTEXT_KEY, 0, batch1) == "on"
    assert forge_value(p, generate.LORA_SYNC_INFOTEXT_KEY, 0, p.all_prompts) is None


def test_loopback_clears_key_and_copy_rerun_keeps_it():
    ad = hooked()
    p = FakeP("m, <lora:Main:1>")
    run(p, {}, (-1, True, True))
    ad.postprocess_image(p, None, FakeArgs("face"))
    assert generate.LORA_SYNC_INFOTEXT_KEY in p.extra_generation_params
    # ADetailer's own re-run on copy(p) (shared extra_generation_params) must keep the key.
    p.all_prompts = list(p.all_prompts)
    assert run(copy.copy(p), {}, (-1, True, True)) == []
    assert generate.LORA_SYNC_INFOTEXT_KEY in p.extra_generation_params
    # A second run on the same p with changed prompts (Loopback) starts without it.
    p.prompt = "other, <lora:Main:1>"
    p.setup_prompts()
    run(p, {}, (-1, True, True))
    assert generate.LORA_SYNC_INFOTEXT_KEY not in p.extra_generation_params
    assert getattr(p, adetailer.LORA_SYNC_ATTR).changed == {}


def test_calls_outside_inner_pass_through():
    ad = hooked()
    p = FakeP("m, <lora:Main:1>")
    run(p, {}, (-1, True, True))
    result = ad.get_prompt(p, FakeArgs("face, <lora:F:1>"))
    assert result == (["face, <lora:F:1>"], ["neg, <lora:N:1>"])


def test_sync_error_returns_parts_before_sync_and_warns_once(monkeypatch):
    ad, warnings = FakeADetailer(), []
    assert adetailer.install(ad, warnings.append)
    p = FakeP("~saber, <lora:Main:1>")
    run(p, BLOCKS, (7, True, True))

    def boom(*_a):
        raise ValueError("bad")
    monkeypatch.setattr(adetailer, "sync_loras", boom)
    ad.postprocess_image(p, None, FakeArgs("face"), FakeArgs("hand, <lora:H:1>"))
    assert ad.seen[0][1][0] == ["face, blonde hair, <lora:FaceS:1>"]  # additions kept
    assert ad.seen[1][1][0] == ["hand, <lora:H:1>"]
    assert len(warnings) == 1 and warnings[0].startswith(adetailer.SYNC_WARN_PREFIX)
    assert warnings[0].isascii()
    assert generate.LORA_SYNC_INFOTEXT_KEY not in p.extra_generation_params


def test_setup_lora_sync_never_raises():
    logs = []

    def bad():
        raise RuntimeError("x")
    p = FakeP("m")
    assert generate.setup_lora_sync(p, True, bad, logs.append) is None
    assert logs and logs[0].startswith("[PromptBlocks]")
    assert generate.setup_lora_sync(p, False, lambda: True) is None
