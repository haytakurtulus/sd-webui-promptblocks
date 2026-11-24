"""Block bans, step 4 (design notes section 38, "Side systems: ADetailer"): ADetailer texts are resolved
under the ban set of the image's positive prompt."""

import copy
import random

from pb_core import adetailer, bans, generate, parser, picks, state

BLOCKS = {
    "ninja": {"category": "PCharacter", "text": "ninja, mask", "bans": ["%PEmotion"],
                "adetailer": ["wolf mask", "", "", ""]},
    "saber": {"category": "PCharacter", "text": "1girl, saber", "adetailer": ["blonde", "", "", ""]},
    "happy": {"category": "PEmotion", "text": "smile", "adetailer": ["happy face", "", "", ""],
              "subs": [{"name": "big", "text": "grin", "mode": "exclude", "slot": None}]},
    "sad": {"category": "PEmotion", "text": "tears"},
    "angry": {"category": "PEmotion", "text": "frown"},
    "facer": {"category": "PFace", "text": "detailed face", "adetailer": ["face, %PEmotion", "", "", ""]},
}


def with_changes(**changes):
    blocks = copy.deepcopy(BLOCKS)
    for name, fields in changes.items():
        blocks.setdefault(name, {}).update(fields)
    return blocks


def run(prompt, blocks, seed):
    uses = []
    out = parser.expand(prompt, blocks, random.Random(seed), uses=uses)
    return out, uses


def tab1(additions):
    return additions[0]


# ---------------------------------------------------------------- acceptance 1: %Category silenced

def test_banned_category_in_adetailer_text_is_silenced_with_clean_separators():
    for seed in range(20):
        out, uses = run("~ninja, ~facer", BLOCKS, seed)
        adds = adetailer.image_additions(BLOCKS, uses, seed)
        assert tab1(adds) == [("ninja", "wolf mask"), ("facer", "face")]


def test_silenced_texts_reach_the_hooked_parts_and_keep_the_panel_prompt():
    out, uses = run("~ninja, ~facer", BLOCKS, 3)
    adds = tab1(adetailer.image_additions(BLOCKS, uses, 3))
    # ADetailer's own panel prompt "(own text)" stays, our texts are appended after it.
    assert adetailer.assign(["own text", "[SKIP]"], adds) == ["own text, wolf mask, face", "[SKIP]"]


def test_text_that_is_empty_after_silencing_adds_nothing():
    blocks = with_changes(facer={"adetailer": ["%PEmotion", "", "", ""]})
    out, uses = run("~ninja, ~facer", blocks, 1)
    assert tab1(adetailer.image_additions(blocks, uses, 1)) == [("ninja", "wolf mask")]
    # Only the silenced text: no addition at all -> nothing stored.
    blocks = with_changes(facer={"adetailer": ["(%PEmotion:1.2)", "", "", ""]},
                          ninja={"adetailer": []})
    out, uses = run("~ninja, ~facer", blocks, 1)
    assert adetailer.all_additions(blocks, [uses], [1]) is None


# ---------------------------------------------------------------- acceptance 2: ~name silenced, forced picks

def test_banned_block_in_adetailer_text_is_silenced():
    blocks = with_changes(ninja={"bans": ["~happy"]},
                          facer={"adetailer": ["face, ~happy, ~happy.big, sharp", "", "", ""]})
    out, uses = run("~ninja, ~facer", blocks, 0)
    assert tab1(adetailer.image_additions(blocks, uses, 0))[1] == ("facer", "face, sharp")


def test_category_in_adetailer_text_uses_the_forced_pick_which_is_never_banned():
    blocks = with_changes(ninja={"bans": ["~happy"]})
    seen = set()
    for seed in range(60):
        out, uses = run("~ninja, %PEmotion, ~facer", blocks, seed)
        pick = adetailer.category_picks(uses)["PEmotion"]
        assert pick != "happy"
        seen.add(pick)
        text = dict(tab1(adetailer.image_additions(blocks, uses, seed)))["facer"]
        assert text == "face, " + blocks[pick]["text"]
    assert seen == {"sad", "angry"}


def test_forced_pick_banned_later_in_the_prompt_is_silenced_not_redrawn():
    # left wins in the main prompt (happy is used, then ~blocker bans it); the ADetailer text uses the
    # final ban set, so %PEmotion there gives nothing instead of happy.
    blocks = with_changes(blocker={"category": "X", "text": "b", "bans": ["~happy"]},
                          wrap={"category": "X", "text": "~happy, ~blocker"})
    out, uses = run("~wrap, ~facer", blocks, 0)
    assert "smile" in out
    assert adetailer.category_picks(uses) == {}
    ev = []
    adds = adetailer.image_additions(blocks, uses, 0, ban_events=ev)
    # happy was used, so its own ADetailer text is still added (it is in the main prompt).
    assert ("happy", "happy face") in tab1(adds)
    blocks["wrap"]["text"] = "%PEmotion, ~blocker"
    for seed in range(40):
        out, uses = run("~wrap, ~facer", blocks, seed)
        if adetailer.category_picks(uses).get("PEmotion") == "happy":
            ev = []
            facer = dict(tab1(adetailer.image_additions(blocks, uses, seed, ban_events=ev)))["facer"]
            assert facer == "face"
            assert any(e["kind"] == "silenced" and e.get("via") == "%PEmotion" for e in ev)
            break
    else:
        raise AssertionError("no seed picked happy")


def test_own_bans_apply_to_the_own_adetailer_text():
    # User decision: ninja bans %PEmotion -> a %PEmotion in ninja's own ADetailer text is silenced,
    # like in its main text. Blocks of ninja's own banned category are silenced too, but a ~ninja
    # token is never silenced by ninja's own bans.
    blocks = with_changes(ninja={"adetailer": ["wolf mask, %PEmotion, ~ninja_extra, ~ninja.eye",
                                                 "", "", ""],
                                   "bans": ["%PEmotion", "%PCharacter"],
                                   "subs": [{"name": "eye", "text": "red eyes", "mode": "exclude",
                                             "slot": None}]},
                          ninja_extra={"category": "PCharacter", "text": "claws"})
    for seed in range(10):
        out, uses = run("~ninja", blocks, seed)
        assert dict(tab1(adetailer.image_additions(blocks, uses, seed)))["ninja"] == "wolf mask, red eyes"


def test_own_ban_only_text_adds_nothing():
    blocks = with_changes(ninja={"adetailer": ["%PEmotion", "", "", ""]})
    out, uses = run("~ninja", blocks, 0)
    assert adetailer.all_additions(blocks, [uses], [0]) is None


# ---------------------------------------------------------------- acceptance 3: batch, each image its own set

def test_batch_each_image_gets_its_own_ban_set():
    prompts = ["%PCharacter, ~facer"] * 40
    seeds = list(range(100, 140))
    uses = []
    picks.expand_recorded(prompts, seeds, BLOCKS, uses=uses)
    table = adetailer.all_additions(BLOCKS, uses, seeds)
    chars = set()
    for i, row in enumerate(table):
        char = adetailer.category_picks(uses[i])["PCharacter"]
        chars.add(char)
        facer = dict(row[0])["facer"]
        if char == "ninja":
            assert facer == "face"
            assert row[0][0] == ("ninja", "wolf mask")
        else:
            # No ban in this image: the same text as resolved without any bans.
            want = parser.expand("face, %PEmotion", BLOCKS, random.Random(seeds[i]), lora=False,
                                 forced=adetailer.category_picks(uses[i]), apply_bans=False).strip()
            assert facer == want and facer != "face"
    assert chars == {"ninja", "saber"}


def test_generate_stores_per_image_additions_and_infotext_shows_silenced_result(monkeypatch):
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})
    monkeypatch.setattr(state, "last_generated", {"txt2img": False, "img2img": False})

    class P:
        pass

    p = P()
    p.all_prompts = ["~ninja, ~facer", "~saber, ~facer"]
    p.all_negative_prompts = ["", ""]
    p.prompt = p.all_prompts[0]
    p.extra_generation_params = {}
    p.iteration, p.batch_size = 0, 2
    generate.process(p, "txt2img", [5, True, False], lambda: copy.deepcopy(BLOCKS), lambda: True)
    table = getattr(p, adetailer.P_ATTR)
    assert table[0][0] == [("ninja", "wolf mask"), ("facer", "face")]
    assert table[1][0][0] == ("saber", "blonde")
    assert table[1][0][1][1].startswith("face, ") and len(table[1][0][1][1]) > len("face, ")

    # The hook appends and records; the infotext key reads only the records.
    hook = adetailer.HookState()
    wrapped = adetailer.make_get_prompt_wrapper(lambda p_, args: (["panel"], [""]), hook)
    hook.n = 0
    for b in (0, 1):
        p.batch_index = b
        parts, _ = wrapped(p, None)
        if b == 0:
            assert parts == ["panel, wolf mask, face"]
    info = p.extra_generation_params[adetailer.INFOTEXT_KEY]
    assert info(p=p, index=0, all_prompts=p.all_prompts) == "1st: wolf mask, face"
    assert "%" not in info(p=p, index=1, all_prompts=p.all_prompts)


# ---------------------------------------------------------------- acceptance 4: no bans -> as before

def _legacy_image_additions(blocks, uses, seed):
    # The step-3 implementation: resolve_text with apply_bans=False.
    forced = adetailer.category_picks(uses)
    result = [[] for _ in range(adetailer.TABS)]
    for name in adetailer.used_blocks(uses):
        block = blocks.get(name)
        if not isinstance(block, dict):
            continue
        for k, raw in adetailer.adetailer_texts(block):
            text = parser.expand(raw, blocks, random.Random(seed), lora=False, forced=forced,
                                 apply_bans=False).strip()
            if text:
                result[k].append((name, text))
    return result


def test_no_bans_reachable_gives_the_same_additions_as_before():
    plain = copy.deepcopy(BLOCKS)
    plain["ninja"].pop("bans")
    plain["other"] = {"category": "PFace", "text": "eyes, %PEmotion",
                      "adetailer": ["", "%PCharacter, ~happy.big, ~happy", "%PEmotion", "x"]}
    for prompt in ("~ninja, ~facer", "%PCharacter, %PEmotion, ~facer, %PFace", "~other, ~happy"):
        for seed in range(30):
            out, uses = run(prompt, plain, seed)
            assert bans.used_bans(plain, uses) == {}
            assert adetailer.image_additions(plain, uses, seed) == _legacy_image_additions(plain, uses, seed)


def test_resolve_text_without_bans_is_the_fast_path():
    plain = copy.deepcopy(BLOCKS)
    plain["ninja"].pop("bans")
    for seed in range(20):
        for b in (None, {}, {"ninja": []}):
            assert adetailer.resolve_text("face, %PEmotion, %PCharacter", plain, seed, {}, b) == \
                parser.expand("face, %PEmotion, %PCharacter", plain, random.Random(seed), lora=False,
                              forced={}, apply_bans=False).strip()


# ---------------------------------------------------------------- the image's ban set

def test_used_bans_is_the_final_active_set(monkeypatch):
    # bans.used_bans(uses) equals the BanState's active banners when the expansion ended, also with
    # redraws, silenced calls and pre-scan clean-ups (random ban graphs).
    states = []
    original = bans.BanState

    class Recording(original):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            states.append(self)

    monkeypatch.setattr(bans, "BanState", Recording)
    r = random.Random(11)
    cats = ["C0", "C1", "C2", "C3"]
    checked = 0
    for _ in range(120):
        blocks = {}
        for i in range(10):
            b = {"category": cats[i % 4], "text": r.choice([f"t{i}", f"t{i}, %{r.choice(cats)}",
                                                             f"~n{r.randrange(10)}"])}
            if r.random() < 0.6:
                b["bans"] = sorted({r.choice([f"~n{r.randrange(10)}", "%" + r.choice(cats)])
                                    for _ in range(r.randint(1, 3))})
            blocks[f"n{i}"] = b
        prompt = ", ".join(r.choice(["%" + c for c in cats] + [f"~n{r.randrange(10)}"])
                           for _ in range(r.randint(2, 6)))
        for seed in range(5):
            states.clear()
            uses = []
            try:
                parser.expand(prompt, blocks, random.Random(seed), uses=uses)
            except parser.BlockCycleError:
                continue
            want = {n: v[1] for n, v in states[0].active.items()} if states else {}
            assert bans.used_bans(blocks, uses) == want
            checked += 1
    assert checked > 300


def test_normalize_initial_and_expand_bans_argument():
    assert bans.normalize_initial(None) == {}
    assert bans.normalize_initial({"a": ["~x", "bad", "~x"], "b": [], 3: ["~y"], "c": "~z"}) == {"a": ["~x"]}
    # Initial bans alone (no reachable banner) take the ban path.
    plain = copy.deepcopy(BLOCKS)
    plain["ninja"].pop("bans")
    ev = []
    assert parser.expand("a, ~happy, b", plain, random.Random(0), bans={"ninja": ["~happy"]},
                         ban_events=ev) == "a, b"
    assert ev == [{"kind": "silenced", "by": ["ninja"], "token": "~happy"}]
    # apply_bans=False ignores them.
    assert parser.expand("~happy", plain, random.Random(0), bans={"k": ["~happy"]}, apply_bans=False) == "smile"


# ---------------------------------------------------------------- preview

def test_preview_ban_lines_for_adetailer_texts():
    out, uses = run("~ninja, ~facer", BLOCKS, 0)
    ev = []
    adetailer.image_additions(BLOCKS, uses, 0, ban_events=ev)
    assert adetailer.preview_ban_lines(ev) == ["⛔ ADetailer: ninja: %PEmotion silenced"]
    assert adetailer.preview_ban_lines([]) == []
