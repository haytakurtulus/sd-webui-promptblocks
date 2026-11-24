"""Small fixes after the ADetailer Stage 1 test (design notes section 33): A re-run guard of process(),
B delete always asks twice, C references inside ADetailer texts, D category messages, F infotext key
"PromptBlocks ADetailer"."""

import copy
import json
import re

import pytest

from pb_core import adetailer, create, formsave, generate, parser, state, subrows, suggest

BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber", "adetailer": ["blonde hair, %PEmo", "", "", ""],
              "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": None}]},
    "rin": {"category": "PChar", "text": "1girl, rin"},
    "happy": {"category": "PEmo", "text": "smile"},
    "sad": {"category": "PEmo", "text": "tears"},
    "neg": {"category": "Neg", "text": "lowres"},
}


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})
    monkeypatch.setattr(state, "last_generated", {"txt2img": False, "img2img": False})


class FakeP:
    """The parts of a StableDiffusionProcessing object that generate.process() reads / writes."""

    def __init__(self, prompt, negative="", n=2, hr=False):
        self.prompt = prompt
        self.negative_prompt = negative
        self.n = n
        self.hr = hr
        self.extra_generation_params = {}
        self.setup_prompts()

    def setup_prompts(self):
        # Like processing.setup_prompts(): fresh template lists (Loopback / SD upscale reuse the same p).
        self.all_prompts = [self.prompt] * self.n
        self.all_negative_prompts = [self.negative_prompt] * self.n
        if self.hr:
            self.all_hr_prompts = [self.prompt] * self.n
            self.all_hr_negative_prompts = [self.negative_prompt] * self.n


def run(p, blocks=BLOCKS, seed=7, add_ad=True, hook=True, log=None):
    calls = []
    generate.process(p, "txt2img", (seed, add_ad), lambda: blocks,
                     hook_ready=lambda: calls.append(1) or hook, log=log or (lambda *a: None))
    return calls


def snapshot(p):
    return (copy.deepcopy(state.last_picks), copy.deepcopy(state.last_generated),
            copy.deepcopy(p.extra_generation_params), copy.deepcopy(getattr(p, adetailer.P_ATTR, None)),
            list(p.all_prompts), list(p.all_negative_prompts))


def adetailer_rerun(p):
    """What ADetailer's postprocess_image does at the last batch index: preserve_prompts() puts equal
    COPIES of the prompt lists back, then process() runs on copy(p) (shared extra_generation_params)."""
    p.all_prompts = list(p.all_prompts)
    p.all_negative_prompts = list(p.all_negative_prompts)
    copy_p = copy.copy(p)
    # A second process() that would run: last_picks / generated flag reset by the copy.
    return copy_p


# ---------------------------------------------------------------- A: re-run guard

def test_second_process_on_copy_changes_nothing():
    p = FakeP("%PChar, %PEmo, ~saber", negative="~neg", hr=True)
    run(p)
    assert state.last_picks["txt2img"] and state.last_generated["txt2img"] is True
    assert getattr(p, adetailer.P_ATTR)  # ADetailer table stored
    assert generate.PICKS_INFOTEXT_KEY in p.extra_generation_params
    assert generate.ADETAILER_INFOTEXT_KEY in p.extra_generation_params
    before = snapshot(p)

    copy_p = adetailer_rerun(p)
    calls = run(copy_p, seed=99)  # another seed: a real re-run would pick differently
    assert calls == []  # not even the ADetailer hook is touched
    assert snapshot(p) == before
    assert getattr(copy_p, adetailer.P_ATTR) == before[3]
    assert copy_p.all_prompts == before[4]


def test_rerun_guard_also_when_nothing_random_was_picked():
    # A prompt without random tokens: last_picks stays [] and the generated flag True.
    p = FakeP("~rin")
    run(p)
    before = snapshot(p)
    assert before[0]["txt2img"] == [] and before[1]["txt2img"] is True
    run(adetailer_rerun(p))
    assert snapshot(p) == before


def test_fresh_p_still_works_normally():
    p1 = FakeP("%PEmo", n=1)
    run(p1, seed=1)
    first = list(state.last_picks["txt2img"])
    p2 = FakeP("%PEmo", n=1)  # a new Generate: a new p, no marker
    state.last_picks["txt2img"] = []
    run(p2, seed=1)
    assert state.last_picks["txt2img"] == first and first
    assert p2.all_prompts == p1.all_prompts and p2.all_prompts[0] in ("smile", "tears")


def test_same_p_with_fresh_template_prompts_is_expanded_again():
    # Loopback / SD upscale / Outpainting call process_images() again on the SAME p; setup_prompts()
    # puts the template back, which must be expanded again (also a negative-only template).
    p = FakeP("~rin", negative="~neg", n=1)
    run(p)
    assert p.all_prompts == ["1girl, rin"] and p.all_negative_prompts == ["lowres"]
    p.setup_prompts()
    run(p)
    assert p.all_prompts == ["1girl, rin"] and p.all_negative_prompts == ["lowres"]

    p = FakeP("plain prompt", negative="~neg", n=1)
    run(p)
    p.setup_prompts()
    assert p.all_negative_prompts == ["~neg"]
    run(p)
    assert p.all_negative_prompts == ["lowres"]


def test_already_processed_decision():
    p = FakeP("~rin", n=1)
    assert not generate.already_processed(p)
    run(p)
    assert generate.already_processed(p)
    assert generate.already_processed(copy.copy(p))
    c = copy.copy(p)
    c.all_prompts = ["~rin"]
    assert not generate.already_processed(c)
    assert not generate.already_processed(FakeP("~rin", n=1))


def test_cycle_error_leaves_prompts_and_records_nothing():
    blocks = {"a": {"category": "C", "text": "~b"}, "b": {"category": "C", "text": "~a"}}
    logs = []
    p = FakeP("~a", n=1)
    run(p, blocks=blocks, log=logs.append)
    assert p.all_prompts == ["~a"] and logs and "ERROR" in logs[0]
    assert getattr(p, adetailer.P_ATTR, None) is None
    for key in (generate.PICKS_INFOTEXT_KEY, generate.TEMPLATE_INFOTEXT_KEY, generate.SEED_INFOTEXT_KEY,
                generate.ADETAILER_INFOTEXT_KEY):
        assert key not in p.extra_generation_params
    # Design notes 35: the error path is marked as well, so ADetailer's re-run on copy(p) does not log the
    # error again and cannot remove the LoRA sync key from the shared extra_generation_params.
    assert generate.already_processed(p)
    run(adetailer_rerun(p), blocks=blocks, log=logs.append)
    assert len(logs) == 1


# ---------------------------------------------------------------- F: infotext key

def test_infotext_summary_format():
    row = [[("saber", "(blue skin)"), ("face", "(closed eyes)")], [], [("rin", "long hair")], []]
    assert adetailer.infotext_summary(row) == "1st: (blue skin), (closed eyes); 3rd: long hair"
    assert adetailer.infotext_summary([[], [], [], []]) == ""
    assert adetailer.infotext_summary(None) == ""
    assert adetailer.infotext_summary([[("x", "a\nb ")], [], [], []]) == "1st: a b"


def test_infotext_values_per_image_and_none():
    # Section 34 replaced the list by an ImageInfotext over the hook's records (job-wide index -> row).
    fn = generate.ImageInfotext({0: [[("saber", "x")], [], [], []], 1: [[], [], [], []]},
                                adetailer.infotext_summary)
    p = FakeP("x", n=2)
    p.iteration, p.batch_size = 0, 2
    assert [fn(p=p, index=i, all_prompts=p.all_prompts) for i in range(2)] == ["1st: x", None]


def test_infotext_key_written_only_with_additions():
    p = FakeP("~saber, %PEmo", n=2)
    run(p)
    fn = p.extra_generation_params[generate.ADETAILER_INFOTEXT_KEY]
    p.iteration, p.batch_size = 0, 2
    # Section 34 B: nothing appended by the hook yet -> no value for any image.
    assert [fn(p=p, index=i, all_prompts=p.all_prompts) for i in range(2)] == [None, None]
    table = getattr(p, adetailer.P_ATTR)
    for i in range(2):  # what the hook records when it appends tab 1 of image i
        p.batch_index = i
        adetailer.record_applied(p, 0, table[i][0])
    for i in range(2):
        emo = "smile" if "smile" in p.all_prompts[i] else "tears"
        assert fn(p=p, index=i, all_prompts=p.all_prompts) == f"1st: blonde hair, {emo}"  # this image's pick
    for add_ad, hook in ((False, True), (True, False)):
        p = FakeP("~saber", n=1)
        run(p, add_ad=add_ad, hook=hook)  # checkbox off / ADetailer absent or hook failed
        assert generate.ADETAILER_INFOTEXT_KEY not in p.extra_generation_params
    p = FakeP("~rin", n=1)
    run(p)
    assert generate.ADETAILER_INFOTEXT_KEY not in p.extra_generation_params


def test_infotext_key_not_restored_on_paste():
    # Information only: the Script registers only the seed key for paste (scripts/promptblocks.py
    # infotext_fields); the key name is distinct from it.
    assert generate.ADETAILER_INFOTEXT_KEY == "PromptBlocks ADetailer" != generate.SEED_INFOTEXT_KEY


# Copied from Forge modules/infotext_utils.py (quote(), re_param_code) to check that the value survives
# Forge's infotext writing (create_infotext: f"{k}: {quote(v)}" joined with ", ") and parsing.
_RE_PARAM = re.compile(r'\s*(\w[\w \-/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')


def _forge_quote(text):
    if ',' not in str(text) and '\n' not in str(text) and ':' not in str(text):
        return text
    return json.dumps(text, ensure_ascii=False)


def _forge_unquote(text):
    if len(text) == 0 or text[0] != '"' or text[-1] != '"':
        return text
    try:
        return json.loads(text)
    except Exception:
        return text


@pytest.mark.parametrize("texts", [
    ["(blue skin), (closed eyes)", "long hair"],
    ['say "hi": 1, <lora:x:0.8>', "a; b"],
    ["ünïcode, ⚠"],
])
def test_infotext_value_survives_forge_quoting(texts):
    row = [[("b", t)] for t in texts] + [[] for _ in range(adetailer.TABS - len(texts))]
    value = adetailer.infotext_summary(row)
    line = ", ".join(f"{k}: {_forge_quote(v)}" for k, v in
                     [("Steps", 20), (generate.ADETAILER_INFOTEXT_KEY, value),
                      (generate.PICKS_INFOTEXT_KEY, "PChar=saber, subs: saber.armor"), ("Seed", 1)])
    parsed = {k.strip(): _forge_unquote(v) for k, v in _RE_PARAM.findall(line)}
    assert parsed[generate.ADETAILER_INFOTEXT_KEY] == value
    assert parsed["Seed"] == "1" and parsed["Steps"] == "20"


# ---------------------------------------------------------------- B: delete asks twice

def test_delete_unused_block_asks_once_more():
    assert suggest.delete_warnings(BLOCKS, "rin") == []
    assert suggest.delete_confirm_message(BLOCKS, "rin") == \
        "⚠ Delete block `rin`? **Press Delete again to confirm.**"


def test_delete_used_block_keeps_its_warning_text():
    blocks = dict(BLOCKS, scene={"category": "S", "text": "~rin"})
    w = suggest.delete_warnings(blocks, "rin")
    assert w == ["`~rin` is used by: scene"]
    assert suggest.delete_confirm_message(blocks, "rin") == \
        "⚠ `~rin` is used by: scene. **Press Delete again to confirm.**"


# ---------------------------------------------------------------- C: references in ADetailer texts

def test_users_of_sees_adetailer_texts():
    blocks = {
        "saber": {"category": "PChar", "text": "saber"},
        "face": {"category": "F", "text": "f", "adetailer": ["", "~saber, %PEmo", "", ""]},
        "happy": {"category": "PEmo", "text": "smile"},
        "self": {"category": "F", "text": "s", "adetailer": ["~self", "", "", ""]},
    }
    assert suggest.users_of(blocks, parser.BLOCK_SYMBOL, "saber") == ["face"]
    assert suggest.users_of(blocks, parser.CATEGORY_SYMBOL, "PEmo") == ["face"]
    assert suggest.users_of(blocks, parser.BLOCK_SYMBOL, "self", exclude="self") == []
    assert suggest.delete_warnings(blocks, "saber") == ["`~saber` is used by: face"]
    # Last active block of %PEmo, referenced only inside an ADetailer text.
    w = suggest.delete_warnings(blocks, "happy")
    assert len(w) == 1 and "`%PEmo`" in w[0] and "face" in w[0]


def test_sub_users_sees_adetailer_texts_including_the_parents_own():
    blocks = {
        "saber": {"category": "P", "text": "saber",
                  "subs": [{"name": "armor", "text": "A", "mode": "include", "slot": None}],
                  "adetailer": ["~saber.armor", "", "", ""]},
        "face": {"category": "F", "text": "f", "adetailer": ["", "", "", "~saber.armor"]},
    }
    assert suggest.sub_users(blocks, "saber", "armor") == ["face", "saber"]


def test_save_removing_a_sub_referenced_in_an_adetailer_text_asks_to_confirm():
    blocks = {
        "saber": {"category": "PChar", "text": "1girl, saber",
                  "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": None}]},
        "face": {"category": "F", "text": "f", "adetailer": ["~saber.armor", "", "", ""]},
    }
    values = subrows.form_values(subrows.block_form(blocks, "saber"), with_chance=True)
    nf = len(subrows.FORM_FIELDS)
    values[nf] = ""  # clear the first sub-block row's name
    values[nf + subrows.ROW_COUNT] = ""  # and its text: the row is removed
    plan = formsave.plan_form_save(blocks, values, "saber")
    assert plan["error"] and "removes a referenced sub-block" in plan["error"]
    assert "`~saber.armor` is used by: face" in plan["error"]


# ---------------------------------------------------------------- D: category messages

@pytest.mark.parametrize("cat, msg", [
    ("", "Category is empty."),
    ("9Cat", "Invalid category: `9Cat` (must start with a letter; letters, digits, _)"),
    ("Ok_1", None),
])
def test_category_error(cat, msg):
    assert parser.category_error(cat) == msg


def test_category_messages_in_formsave_and_create():
    values = subrows.form_values(subrows.block_form(BLOCKS, "rin"), with_chance=True)
    i = subrows.FORM_FIELDS.index("category")
    for cat, msg in (("  ", "Category is empty."),
                     ("a-b", "Invalid category: `a-b` (must start with a letter; letters, digits, _)")):
        values[i] = cat
        assert formsave.plan_form_save(BLOCKS, values, "rin")["error"] == msg
        assert create.build_new_block(BLOCKS, "newb", cat, "t") == (None, msg)
