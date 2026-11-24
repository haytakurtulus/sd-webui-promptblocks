"""ADetailer text per block, Stage 1 (design notes sections 31 and 31a): stored field, block uses,
additions, assign(), form / save / snapshot, rename / health / preview, and the runtime hook on fake
ADetailer objects."""

import json
import random
import re

import pytest

from pb_core import adetailer, bulk, formsave, guard, health, parser, picks, storage, subrows, subs

NF = len(subrows.FORM_FIELDS)


# ---------------------------------------------------------------- stored field

def test_block_adetailer_defaults_and_normalisation():
    assert adetailer.block_adetailer({"text": "x"}) == ["", "", "", ""]
    assert adetailer.block_adetailer(None) == ["", "", "", ""]
    assert adetailer.block_adetailer({"adetailer": "nope"}) == ["", "", "", ""]
    assert adetailer.block_adetailer({"adetailer": [" a ", 3, None]}) == ["a", "", "", ""]
    assert adetailer.block_adetailer({"adetailer": ["a", "b", "c", "d", "e"]}) == ["a", "b", "c", "d"]


def test_set_block_adetailer_omits_when_all_empty():
    b = {"category": "P", "text": "t", "adetailer": ["x", "", "", ""]}
    new = adetailer.set_block_adetailer(b, ["", "  ", None, ""])
    assert "adetailer" not in new
    assert b["adetailer"] == ["x", "", "", ""]  # input untouched
    new = adetailer.set_block_adetailer({"text": "t"}, [" a ", "", "b"])
    assert new["adetailer"] == ["a", "", "b", ""]


def test_old_blocks_json_loads_and_saves_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "DATA_FILE", str(tmp_path / "data" / "blocks.json"))
    old = {"saber": {"category": "PChar", "text": "1girl, saber"}}
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "blocks.json").write_text(json.dumps({"version": 1, "blocks": old}), "utf-8")
    blocks = storage.load_blocks()
    assert blocks == old
    form = subrows.form_values(subrows.block_form(blocks, "saber"), with_chance=True)
    assert [form[subrows.FORM_FIELDS.index(f)] for f in subrows.ADETAILER_FIELDS] == ["", "", "", ""]
    plan = formsave.plan_form_save(blocks, form, "saber")
    assert plan["error"] is None and plan["blocks"]["saber"] == old["saber"]
    storage.save_blocks(plan["blocks"])
    saved = json.loads((tmp_path / "data" / "blocks.json").read_text("utf-8"))
    assert saved == {"version": 1, "blocks": old}


def test_ignored_details():
    assert adetailer.ignored_details({"text": "x"}) == []
    assert adetailer.ignored_details({"adetailer": None}) == []
    assert adetailer.ignored_details({"adetailer": ["a", "", None, ""]}) == []
    assert "not a list" in adetailer.ignored_details({"adetailer": "a"})[0]
    d = adetailer.ignored_details({"adetailer": ["a", 5, "", "", "extra", ""]})
    assert len(d) == 2 and "2nd" in d[0] and "#5" in d[1]


# ---------------------------------------------------------------- block uses (rule 1)

USES_BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber, ~eyes", "lora": "<lora:s:1>",
              "subs": [{"name": "armor", "text": "ARMOR", "slot": "outfit"},
                       {"name": "dress", "text": "DRESS, ~eyes", "slot": "outfit"}]},
    "rin": {"category": "PChar", "text": "rin, %PEmo"},
    "eyes": {"category": "Parts", "text": "green eyes"},
    "smile": {"category": "PEmo", "text": "smile"},
    "angry": {"category": "PEmo", "text": "angry, ~eyes"},
    "pose": {"category": "PPose", "text": "standing, %PChar"},
}

PROMPTS = ["~pose, %PEmo", "~saber*outfit, ~rin.x, ~saber.armor", "%PChar, %PChar, ~nope, ~saber*none",
           "plain text", "~rin, ~saber.dress"]


def test_uses_do_not_change_output_rng_or_picks():
    for prompt in PROMPTS:
        for seed in range(30):
            r1, r2 = random.Random(seed), random.Random(seed)
            p1, p2, t1, t2 = [], [], [], []
            a = parser.expand(prompt, USES_BLOCKS, r1, trace=t1, picks=p1)
            uses = []
            b = parser.expand(prompt, USES_BLOCKS, r2, trace=t2, picks=p2, uses=uses)
            assert a == b and p1 == p2 and t1 == t2
            assert r1.getstate() == r2.getstate()


def test_uses_are_ordered_with_via_and_depth():
    uses = []
    parser.expand("~saber.armor, ~pose", USES_BLOCKS, random.Random(1), uses=uses)
    assert uses[0] == {"block": "saber", "via": "sub", "depth": 0, "sub": "armor"}
    assert uses[1] == {"block": "pose", "via": "block", "depth": 0}
    assert uses[2]["via"] == "category" and uses[2]["category"] == "PChar" and uses[2]["depth"] == 1
    # The picked character comes before the blocks its text reaches.
    names = [u["block"] for u in uses]
    assert names.index(uses[2]["block"]) == 2


def test_uses_slot_draw_and_lora_rule():
    uses = []
    parser.expand("~saber*outfit", USES_BLOCKS, random.Random(3), uses=uses)
    assert uses[0]["block"] == "saber" and uses[0]["via"] == "slot" and uses[0]["slot"] == "outfit"
    assert uses[0]["sub"] in ("armor", "dress")
    uses = []
    # Unknown sub, empty slot draw, unknown block: nothing inserted, so nothing used (LoRA rule).
    parser.expand("~saber.nope, ~saber*none, ~ghost, %Nope", USES_BLOCKS, random.Random(0), uses=uses)
    assert uses == []
    uses = []
    parser.expand("~saber", USES_BLOCKS, random.Random(0), uses=uses, lora=False)
    assert [u["block"] for u in uses][:2] == ["saber", "eyes"]


def test_expand_recorded_uses_are_index_aligned_and_optional():
    prompts, seeds = ["~rin", "~saber"], [5, 6]
    base = picks.expand_recorded(prompts, seeds, USES_BLOCKS)
    uses = []
    again = picks.expand_recorded(prompts, seeds, USES_BLOCKS, uses=uses)
    assert again == base
    assert [u[0]["block"] for u in uses] == ["rin", "saber"]


def test_forced_category_uses_no_rng_at_any_depth():
    r = random.Random(9)
    before = r.getstate()
    out = parser.expand("%PEmo and ~rin", USES_BLOCKS, r, forced={"PEmo": "angry"})
    assert out == "angry, green eyes and rin, angry, green eyes"
    assert r.getstate() == before
    # A forced block that does not exist is ignored (normal pick).
    out = parser.expand("%PEmo", USES_BLOCKS, random.Random(0), forced={"PEmo": "ghost"})
    assert out in ("smile", "angry, green eyes")


# ---------------------------------------------------------------- additions

AD_BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl, saber", "lora": "<lora:saber:1>",
              "adetailer": ["long yellow hair, green eyes, %PEmo", "", "saber hands", ""]},
    "rin": {"category": "PChar", "text": "rin, ~saber", "adetailer": ["rin face", "", "", "rin 4th"]},
    "smile": {"category": "PEmo", "text": "smile", "adetailer": ["SMILE-AD", "", "", ""]},
    "angry": {"category": "PEmo", "text": "angry"},
    "sad": {"category": "PEmo", "text": "sad"},
    "beach": {"category": "Place", "text": "beach"},
    "night": {"category": "Place", "text": "night"},
    "deco": {"category": "Deco", "text": "deco", "adetailer": ["", "", "", ""]},
    "loop": {"category": "Loop", "text": "~loop"},
}


def additions(prompt, seed, blocks=AD_BLOCKS, errors=None):
    uses = []
    parser.expand(prompt, blocks, random.Random(seed), uses=uses)
    return adetailer.image_additions(blocks, uses, seed, errors)


def test_category_pick_of_the_image_is_reused():
    for seed in range(40):
        uses, pk = [], []
        main = parser.expand("~saber, %PEmo", AD_BLOCKS, random.Random(seed), uses=uses, picks=pk)
        emo = pk[0]["block"]
        tab1 = adetailer.image_additions(AD_BLOCKS, uses, seed)[0]
        saber_text = dict(tab1)["saber"]
        assert saber_text == "long yellow hair, green eyes, " + AD_BLOCKS[emo]["text"]
        assert AD_BLOCKS[emo]["text"] in main


def test_nested_category_pick_is_reused():
    # The %PEmo pick happens inside another block's text (depth 1): still reused.
    blocks = dict(AD_BLOCKS, face={"category": "Face", "text": "face, %PEmo"})
    for seed in range(20):
        uses = []
        main = parser.expand("~saber, ~face", blocks, random.Random(seed), uses=uses)
        text = dict(adetailer.image_additions(blocks, uses, seed)[0])["saber"]
        assert text.split(", ")[-1] in main.split(", ")


def test_category_not_in_main_prompt_is_deterministic():
    blocks = dict(AD_BLOCKS, saber=dict(AD_BLOCKS["saber"], adetailer=["at %Place", "", "", ""]))
    seen = set()
    for seed in range(30):
        a = additions("~saber", seed, blocks)[0]
        b = additions("~saber, more text", seed, blocks)[0]
        assert a == b  # the image's block seed, a fresh Random: independent of the main template
        assert a == [("saber", parser.expand("at %Place", blocks, random.Random(seed), lora=False))]
        seen.add(a[0][1])
    assert seen == {"at beach", "at night"}


def test_no_recursive_adetailer_text_and_no_lora():
    # rin's text reaches saber: saber is used too (its ADetailer text is added once, for saber), but
    # expanding rin's / saber's ADetailer texts never adds ADetailer texts of the blocks they reach.
    blocks = dict(AD_BLOCKS, rin=dict(AD_BLOCKS["rin"], adetailer=["~saber face", "", "", ""]))
    tab1 = additions("~rin", 0, blocks)[0]
    assert tab1[0] == ("rin", "1girl, saber face")
    assert "<lora" not in " ".join(t for _, t in tab1)
    assert all("long yellow hair" not in t for n, t in tab1 if n == "rin")


def test_dedupe_and_order_of_first_use():
    tab1 = additions("~rin, ~saber, ~rin, ~smile", 0)[0]
    assert [n for n, _ in tab1] == ["rin", "saber", "smile"]
    tab1 = additions("~smile, ~saber.x, ~saber", 0)[0]
    assert [n for n, _ in tab1] == ["smile", "saber"]


def test_tabs_one_to_four_and_empty_texts_ignored():
    adds = additions("~rin, ~deco, ~angry", 0)
    assert len(adds) == 4
    assert [n for n, _ in adds[0]] == ["rin", "saber"]
    assert adds[1] == []
    assert adds[2] == [("saber", "saber hands")]
    assert adds[3] == [("rin", "rin 4th")]
    assert additions("~deco, ~angry, plain", 0) == [[], [], [], []]


def test_text_that_resolves_to_empty_is_ignored():
    blocks = {"a": {"category": "A", "text": "a", "adetailer": ["%Ghost", "  ", "", ""]},
              "e": {"category": "E", "text": ""},
              "b": {"category": "B", "text": "b", "adetailer": ["~e", "", "", ""]}}
    adds = additions("~a, ~b", 0, blocks)
    assert adds[0] == [("a", "%Ghost")]  # unknown tokens stay (and are reported by the preview)


def test_cycle_in_adetailer_text_is_skipped_with_error():
    blocks = dict(AD_BLOCKS, beach=dict(AD_BLOCKS["beach"], adetailer=["~loop", "", "", ""]))
    errors = []
    adds = additions("~beach, ~smile", 0, blocks, errors)
    assert adds[0] == [("smile", "SMILE-AD")]
    assert len(errors) == 1 and "beach" in errors[0] and "1st" in errors[0]


def test_all_additions_none_when_nothing():
    assert adetailer.all_additions(AD_BLOCKS, [[], []], [1, 2]) is None
    uses = []
    parser.expand("~smile", AD_BLOCKS, random.Random(0), uses=uses)
    table = adetailer.all_additions(AD_BLOCKS, [[], uses], [1, 2])
    assert table[0] == [[], [], [], []] and table[1][0] == [("smile", "SMILE-AD")]


# ---------------------------------------------------------------- assign

def test_assign_appends_to_every_part():
    adds = [("saber", "long hair"), ("rin", "red eyes")]
    assert adetailer.assign(["face a", "face b"], adds) == ["face a, long hair, red eyes",
                                                           "face b, long hair, red eyes"]


def test_assign_empty_part_skip_part_and_trailing_comma():
    adds = [("saber", "long hair")]
    assert adetailer.assign([""], adds) == ["long hair"]
    assert adetailer.assign(["  "], adds) == ["long hair"]
    assert adetailer.assign(["[SKIP]", " [SKIP] ", "x"], adds) == ["[SKIP]", " [SKIP] ", "x, long hair"]
    assert adetailer.assign(["smile, "], adds) == ["smile, long hair"]


def test_assign_without_additions_is_an_unchanged_copy():
    parts = ["a", "b"]
    out = adetailer.assign(parts, [])
    assert out == parts and out is not parts
    assert adetailer.assign(parts, [("x", "  ")]) == parts
    adetailer.assign(parts, [("x", "y")])
    assert parts == ["a", "b"]


# ---------------------------------------------------------------- form / save / snapshot

FORM_BLOCKS = {"saber": {"category": "PChar", "text": "1girl", "adetailer": ["ad one", "", "", "ad four"]}}


def form_values(name="saber", blocks=FORM_BLOCKS):
    return subrows.form_values(subrows.block_form(blocks, name), with_chance=True)


def put(values, field, value):
    values = list(values)
    values[subrows.FORM_FIELDS.index(field)] = value
    return values


def test_form_load_and_blank_form():
    f = subrows.block_form(FORM_BLOCKS, "saber")
    assert [f[k] for k in subrows.ADETAILER_FIELDS] == ["ad one", "", "", "ad four"]
    blank = subrows.blank_form()
    assert [blank[k] for k in subrows.ADETAILER_FIELDS] == ["", "", "", ""]


def test_snapshot_marks_adetailer_change_as_modified():
    v = form_values()
    assert not guard.is_modified(FORM_BLOCKS, "saber", v)
    assert not guard.is_modified(FORM_BLOCKS, "saber", put(v, "adetailer_1", "  ad one "))
    assert guard.is_modified(FORM_BLOCKS, "saber", put(v, "adetailer_2", "new"))
    assert guard.is_modified(FORM_BLOCKS, "saber", put(v, "adetailer_4", ""))


def test_save_stores_and_removes_field():
    plan = formsave.plan_form_save(FORM_BLOCKS, put(form_values(), "adetailer_3", " three "), "saber")
    assert plan["error"] is None
    assert plan["blocks"]["saber"]["adetailer"] == ["ad one", "", "three", "ad four"]
    assert not guard.is_modified(plan["blocks"], "saber", put(form_values(), "adetailer_3", "three"))
    v = form_values()
    for f in subrows.ADETAILER_FIELDS:
        v = put(v, f, "")
    plan = formsave.plan_form_save(FORM_BLOCKS, v, "saber")
    assert "adetailer" not in plan["blocks"]["saber"]


def test_save_as_new_name_keeps_adetailer_texts():
    # Duplicate keeps the form values and sets a new Name; Save then creates the copy with them.
    v = put(form_values(), "name", "saber_copy")
    plan = formsave.plan_form_save(FORM_BLOCKS, v, None)
    assert plan["blocks"]["saber_copy"]["adetailer"] == ["ad one", "", "", "ad four"]


def test_save_refuses_cycle_in_adetailer_text():
    blocks = dict(FORM_BLOCKS, loop={"category": "L", "text": "~loop"})
    plan = formsave.plan_form_save(blocks, put(form_values(blocks=blocks), "adetailer_2", "~loop"), "saber")
    assert plan["error"] and "ADetailer 2nd" in plan["error"]


# ---------------------------------------------------------------- rename / health / preview

REF_BLOCKS = {
    "saber": {"category": "PChar", "text": "1girl", "subs": [{"name": "armor", "text": "ARMOR"}]},
    "rin": {"category": "PChar", "text": "rin", "adetailer": ["~saber, ~saber.armor, %PChar", 7, "", ""]},
    "emo": {"category": "PEmo", "text": "smile"},
}


def test_rename_block_rewrites_adetailer_texts():
    new, updated = subs.rename_block_refs(REF_BLOCKS, "saber", "arturia")
    assert new["rin"]["adetailer"] == ["~arturia, ~arturia.armor, %PChar", 7, "", ""]
    assert updated == ["rin"]
    assert REF_BLOCKS["rin"]["adetailer"][0].startswith("~saber")  # input untouched


def test_rename_sub_rewrites_adetailer_texts():
    new, updated = subrows.rename_sub_refs_many(REF_BLOCKS, "saber", {"armor": "plate"})
    assert new["rin"]["adetailer"][0] == "~saber, ~saber.plate, %PChar" and updated == ["rin"]


def test_rename_category_rewrites_adetailer_texts():
    new, moved, rewritten = bulk.rename_category(REF_BLOCKS, "PChar", "Hero")
    assert new["rin"]["adetailer"][0] == "~saber, ~saber.armor, %Hero"
    assert "rin" in rewritten and sorted(moved) == ["rin", "saber"]


def test_rewrite_keeps_shape_without_field():
    new, changed = subs.rewrite_block_texts({"category": "P", "text": "t"}, lambda t: t)
    assert new == {"category": "P", "text": "t"} and not changed


def test_health_reports_unknown_refs_and_ignored_values_in_adetailer_texts():
    blocks = dict(REF_BLOCKS, rin=dict(REF_BLOCKS["rin"],
                                       adetailer=["~ghost, %Nope, ~saber.x", 7, "", "", "five"]))
    findings = health.report(blocks)
    unknown = [f for f in findings if f["kind"] == "unknown_ref" and f["block"] == "rin"]
    assert len(unknown) == 3 and all(f["detail"].startswith("ADetailer 1st:") for f in unknown)
    ignored = [f["detail"] for f in findings if f["kind"] == "ignored_value" and f["block"] == "rin"]
    assert any("2nd" in d for d in ignored) and any("#5" in d for d in ignored)
    clean = {k: v for k, v in REF_BLOCKS.items() if k != "rin"}
    clean["rin"] = {"category": "PChar", "text": "rin", "adetailer": ["~saber", "", "", ""]}
    assert health.report(clean) == []


def test_health_all_inactive_ref_in_adetailer_text():
    blocks = {"a": {"category": "A", "text": "a", "adetailer": ["%Off", "", "", ""]},
              "b": {"category": "Off", "text": "b", "active": False}}
    f = [x for x in health.report(blocks) if x["kind"] == "all_inactive_ref"]
    assert len(f) == 1 and f[0]["detail"].startswith("ADetailer 1st:")


def test_preview_warnings_and_entries():
    blocks = {"a": {"category": "A", "text": "a", "adetailer": ["~ghost, %Off", "", "x", ""]},
              "b": {"category": "Off", "text": "b", "active": False}}
    adds = additions("~a, ~zzz", 0, blocks)
    text = parser.expand("~a, ~zzz", blocks, random.Random(0))
    unknown, inactive = parser.preview_warnings(text, blocks)
    unknown, inactive = adetailer.preview_warnings(adds, blocks, unknown, inactive)
    assert unknown == ["~zzz", "~ghost"] and inactive == ["Off"]
    assert adetailer.preview_entries(adds) == [
        {"tab": 1, "label": "1st", "items": [{"block": "a", "text": "~ghost, %Off"}]},
        {"tab": 3, "label": "3rd", "items": [{"block": "a", "text": "x"}]}]


# ---------------------------------------------------------------- hook (fake ADetailer)

class FakeArgs:
    def __init__(self, ad_prompt):
        self.ad_prompt = ad_prompt
        self.ad_negative_prompt = "neg"


class FakeP:
    def __init__(self, all_prompts, batch_size=1):
        self.all_prompts = list(all_prompts)
        self.prompt = all_prompts[0]
        self.iteration = 0
        self.batch_index = 0
        self.batch_size = batch_size


class FakeADetailer:
    """The parts of ADetailer 26.2.0 the hook relies on (scripts/!adetailer.py)."""

    def __init__(self):
        self.seen = []  # (n, prompts, negatives) of every get_prompt call inside the inner method

    def title(self):
        return "ADetailer"

    def get_prompt(self, p, args):
        i = p.iteration * p.batch_size + p.batch_index
        parts = re.split(r"\s*\[SEP\]\s*", args.ad_prompt)
        parts = [p.all_prompts[i] if not x else x.replace("[PROMPT]", p.all_prompts[i]) for x in parts]
        return parts, [args.ad_negative_prompt]

    def _postprocess_image_inner(self, p, pp, args, *, n=0):
        prompts, negatives = self.get_prompt(p, args)
        self.seen.append((n, prompts, negatives))
        return True

    def postprocess_image(self, p, pp, *arg_list):
        for n, args in enumerate(arg_list):
            self._postprocess_image_inner(p, pp, args, n=n)


def table_for(*per_image):
    # per_image: list of 4 lists of (name, text)
    return list(per_image)


def test_hook_appends_per_tab_and_image():
    ad, warnings = FakeADetailer(), []
    assert adetailer.install(ad, warnings.append)
    p = FakeP(["main0", "main1"], batch_size=2)
    setattr(p, adetailer.P_ATTR, table_for(
        [[("saber", "long hair")], [], [("saber", "hands")], []],
        [[("rin", "red eyes")], [], [], []]))
    ad.postprocess_image(p, None, FakeArgs("face [SEP] other"), FakeArgs(""), FakeArgs("[PROMPT], hand"))
    assert ad.seen == [(0, ["face, long hair", "other, long hair"], ["neg"]),
                       (1, ["main0"], ["neg"]),
                       (2, ["main0, hand, hands"], ["neg"])]
    ad.seen.clear()
    p.batch_index = 1
    ad.postprocess_image(p, None, FakeArgs(""))
    assert ad.seen == [(0, ["main1, red eyes"], ["neg"])]
    assert warnings == []


def test_hook_leaves_calls_outside_inner_and_without_table_alone():
    ad = FakeADetailer()
    adetailer.install(ad, print)
    p = FakeP(["main"])
    setattr(p, adetailer.P_ATTR, table_for([[("saber", "long hair")], [], [], []]))
    # ADetailer's process() calls get_prompt directly (X/Y/Z prompt S/R): no n -> unchanged.
    assert ad.get_prompt(p, FakeArgs("face")) == (["face"], ["neg"])
    q = FakeP(["main"])  # no table at all (checkbox off / no additions)
    ad.postprocess_image(q, None, FakeArgs("face"))
    assert ad.seen == [(0, ["face"], ["neg"])]
    setattr(q, adetailer.P_ATTR, None)
    ad.postprocess_image(q, None, FakeArgs("face"), FakeArgs("x"), FakeArgs("y"), FakeArgs("z"),
                         FakeArgs("fifth tab"))
    assert [s[1] for s in ad.seen[1:]] == [["face"], ["x"], ["y"], ["z"], ["fifth tab"]]


def test_hook_tab_beyond_four_gets_nothing():
    ad = FakeADetailer()
    adetailer.install(ad, print)
    p = FakeP(["main"])
    setattr(p, adetailer.P_ATTR, table_for([[("a", "A")], [("a", "B")], [("a", "C")], [("a", "D")]]))
    ad.postprocess_image(p, None, *[FakeArgs(f"t{k}") for k in range(5)])
    assert [s[1][0] for s in ad.seen] == ["t0, A", "t1, B", "t2, C", "t3, D", "t4"]


def test_install_is_idempotent():
    ad = FakeADetailer()
    assert adetailer.install(ad, print)
    first_inner, first_gp = ad._postprocess_image_inner, ad.get_prompt
    assert adetailer.install(ad, print)
    assert ad._postprocess_image_inner is first_inner and ad.get_prompt is first_gp
    p = FakeP(["main"])
    setattr(p, adetailer.P_ATTR, table_for([[("a", "A")], [], [], []]))
    ad.postprocess_image(p, None, FakeArgs("x"))
    assert ad.seen == [(0, ["x, A"], ["neg"])]  # appended once, not twice


def test_install_refuses_missing_method_or_bad_signature_once():
    class NoInner:
        def title(self):
            return "ADetailer"

        def get_prompt(self, p, args):
            return ["x"], ["n"]

    class BadSig(FakeADetailer):
        def _postprocess_image_inner(self, p, pp, args):  # no n
            return False

    for cls in (NoInner, BadSig):
        obj, warnings = cls(), []
        before = obj.get_prompt
        assert not adetailer.install(obj, warnings.append)
        assert not adetailer.install(obj, warnings.append)
        assert len(warnings) == 1 and warnings[0].startswith(adetailer.WARN_PREFIX)
        assert obj.get_prompt == before and "get_prompt" not in vars(obj)


def test_error_in_our_part_disables_hook_with_one_line():
    ad, warnings = FakeADetailer(), []
    adetailer.install(ad, warnings.append)
    p = FakeP(["main"])
    setattr(p, adetailer.P_ATTR, [42])  # broken table: our code raises
    ad.postprocess_image(p, None, FakeArgs("face"), FakeArgs("x"))
    assert [s[1] for s in ad.seen] == [["face"], ["x"]]  # ADetailer unchanged
    assert len(warnings) == 1 and warnings[0].startswith(adetailer.WARN_PREFIX)
    # Disabled from now on, even with a good table.
    setattr(p, adetailer.P_ATTR, table_for([[("a", "A")], [], [], []]))
    ad.postprocess_image(p, None, FakeArgs("face"))
    assert ad.seen[-1][1] == ["face"] and len(warnings) == 1


def test_exceptions_of_adetailer_pass_through_and_n_is_cleared():
    class Boom(FakeADetailer):
        def _postprocess_image_inner(self, p, pp, args, *, n=0):
            raise ValueError("adetailer bug")

    ad = Boom()
    adetailer.install(ad, print)
    p = FakeP(["main"])
    setattr(p, adetailer.P_ATTR, table_for([[("a", "A")], [], [], []]))
    with pytest.raises(ValueError, match="adetailer bug"):
        ad._postprocess_image_inner(p, None, FakeArgs("x"), n=0)
    state = getattr(ad, adetailer.HOOK_MARKER)
    assert state.n is None
    assert ad.get_prompt(p, FakeArgs("x")) == (["x"], ["neg"])


def test_find_scripts_and_install_all():
    class Other:
        def title(self):
            return "Other"

    class Broken:
        def title(self):
            raise RuntimeError("no title")

    class Runner:
        def __init__(self, scripts):
            self.scripts = scripts
            self.alwayson_scripts = scripts

    ad = FakeADetailer()
    runners = [None, Runner([Other(), Broken(), ad]), Runner([ad])]
    assert adetailer.find_scripts(runners) == [ad]
    assert adetailer.install_all(runners, print) == 1
    assert adetailer.install_all([None, Runner([Other()])], print) == 0
