"""Block bans at Generate / Preview (design notes section 38, steps 2 and 3; the redraw rules are in
test_bans_redraw.py): fast path, pool filtering, silencing, negative prompts, reporting."""

import copy
import random

import pytest

import legacy_parser_v1 as legacy
from pb_core import adetailer, bans, generate, parser, picks, state


# ---------------------------------------------------------------- acceptance 1: fast path

def _random_blocks(r):
    """A random block set using every expansion feature; plus "loner", a banning block that no other
    block and no generated prompt can reach (its category CL is never referenced). Blocks b0-b2 are in
    CA, b3-b5 in CB, b6-b7 in CC; mostly a block's texts reference later blocks / categories only, so
    most expansions finish (a few reference anything, so cycles are compared too)."""
    names = [f"b{i}" for i in range(8)]
    cats = ["CA", "CB", "CC"]
    group = {n: cats[min(i // 3, 2)] for i, n in enumerate(names)}
    slots = [None, "outfit", "pose"]

    def item(i):
        k = r.random()
        loose = r.random() < 0.05
        later = names if loose else (names[i + 1:] or ["unknown"])
        later_cats = cats if loose else (cats[cats.index(group[names[i]]) + 1:] or ["Nope"])
        n = r.choice(later)
        if k < 0.3:
            return f"tag{r.randrange(20)}"
        if k < 0.5:
            return "~" + n
        if k < 0.7:
            return "%" + r.choice(later_cats + ["Nope"])
        if k < 0.8:
            return f"~{n}.s{r.randrange(3)}"
        if k < 0.9:
            return f"~{n}*{r.choice(['outfit', 'pose', 'none'])}"
        return r.choice(["~unknown", "~_~", "(x:1.2)", "~b0.", "%CA*"])

    def text(i, max_items):
        return ", ".join(item(i) for _ in range(r.randint(0, max_items)))

    blocks = {}
    for i, n in enumerate(names):
        b = {"category": group[n], "text": text(i, 3)}
        if r.random() < 0.3:
            b["weight"] = r.choice([0.5, 2, 3])
        if r.random() < 0.15:
            b["active"] = False
        if r.random() < 0.3:
            b["lora"] = f"<lora:{n}:0.7>"
        if r.random() < 0.6:
            subs = []
            for j in range(r.randint(1, 4)):
                s = {"name": f"s{j}", "text": text(i, 2), "mode": r.choice(["include", "exclude", "random"]),
                     "slot": r.choice(slots)}
                if s["mode"] == "random" and r.random() < 0.5:
                    s["chance"] = r.choice([10, 30, 80])
                subs.append(s)
            b["subs"] = subs
        if r.random() < 0.2:
            b["slot"] = r.choice(["outfit", "pose"])
        if r.random() < 0.15:
            b["bans"] = []  # empty list: same as no bans
        if r.random() < 0.1:
            b["bans"] = "~b1"  # broken stored value: ignored
        if r.random() < 0.1:
            b["bans"] = ["not a token", 3]  # only invalid entries: ignored
        blocks[n] = b
    blocks["loner"] = {"category": "CL", "text": "~b0, %CA, alone", "bans": ["~b0", "%CA", "%CB", "%CC"]}
    return blocks


def _run(module, prompt, blocks, seed, lora, forced):
    rng = random.Random(seed)
    trace, pk, uses = [], [], []
    try:
        out = module.expand(prompt, blocks, rng, trace=trace, lora=lora, picks=pk, uses=uses, forced=forced)
    except module.BlockCycleError as e:
        out = ("cycle", str(e))
    return out, trace, pk, uses, rng.getstate()


def test_fast_path_is_byte_identical_to_the_old_parser():
    r = random.Random(1234)
    compared = 0
    for _ in range(120):
        blocks = _random_blocks(r)
        for _ in range(4):
            prompt = ", ".join(r.choice(["~b0", "~b1", "%CA", "%CB", "%CC", "~b2.s0", "~b3*outfit", "red hair",
                                         "~b4", "%Nope", "~b5.s1", "~b6*pose", "~b7"])
                               for _ in range(r.randint(1, 4)))
            assert not bans.reaches_bans(prompt, blocks)
            forced = r.choice([None, {"CA": "b0"}, {"CB": "b7", "CC": "nope"}])
            for seed in range(8):
                lora = seed % 2 == 0
                old = _run(legacy, prompt, blocks, seed, lora, forced)
                new = _run(parser, prompt, blocks, seed, lora, forced)
                assert new == old, (prompt, seed)
                compared += 1
    assert compared == 120 * 4 * 8


def test_apply_bans_false_is_the_old_parser_even_when_bans_are_reachable():
    r = random.Random(99)
    for _ in range(40):
        blocks = _random_blocks(r)
        blocks["b0"]["bans"] = ["~b1", "%CB"]
        for prompt in ("~b0, %CB, ~b1", "%CA, %CB, %CC", "~loner, ~b2"):
            for seed in range(5):
                rng_old, rng_new = random.Random(seed), random.Random(seed)
                try:
                    old = legacy.expand(prompt, blocks, rng_old)
                except legacy.BlockCycleError:
                    old = "cycle"
                try:
                    new = parser.expand(prompt, blocks, rng_new, apply_bans=False)
                except parser.BlockCycleError:
                    new = "cycle"
                assert new == old and rng_new.getstate() == rng_old.getstate()


def test_reaches_bans():
    blocks = {
        "ninja": {"category": "PChar", "text": "ninja", "bans": ["~happy"]},
        "off": {"category": "PHidden", "text": "x", "active": False, "bans": ["~happy"]},
        "happy": {"category": "PEmo", "text": "smile"},
        "pose": {"category": "PPose", "text": "run, ~ninja"},
        "parent": {"category": "PPose", "text": "p", "lora": "<lora:x~ninja:1>",
                   "subs": [{"name": "s", "text": "%PHidden", "mode": "exclude", "slot": "z"}]},
        "lonely": {"category": "PPose", "text": "lonely"},
    }
    assert bans.reaches_bans("~ninja", blocks)
    assert bans.reaches_bans("%PChar", blocks)
    assert bans.reaches_bans("%PHidden", blocks)  # inactive members count (superset)
    assert bans.reaches_bans("~pose", blocks)  # through a text
    assert bans.reaches_bans("%PPose", blocks)
    assert bans.reaches_bans("~parent", blocks)  # through an excluded sub text
    assert bans.reaches_bans("~parent*z", blocks)
    assert not bans.reaches_bans("~happy, %PEmo, ~lonely, ~unknown, %Nope", blocks)
    assert not bans.reaches_bans("~lonely", {**blocks, "parent": {**blocks["parent"], "subs": []}})
    # A LoRA text is never expanded, so "~ninja" inside it reaches nothing.
    no_sub = {**blocks, "parent": {**blocks["parent"], "subs": []}}
    assert not bans.reaches_bans("~parent", no_sub)
    assert not bans.reaches_bans("~ninja", {"ninja": {"category": "C", "text": "k", "bans": []}})


# ---------------------------------------------------------------- acceptance 2: pool filtering

BLOCKS = {
    "ninja": {"category": "PCharacter", "text": "ninja, mask", "bans": ["~happy"]},
    "saber": {"category": "PCharacter", "text": "1girl, saber"},
    "happy": {"category": "PEmotion", "text": "smile", "lora": "<lora:happy:0.5>",
              "adetailer": ["happy face", "", "", ""],
              "subs": [{"name": "big", "text": "grin", "mode": "include", "slot": None},
                       {"name": "lips", "text": "open mouth", "mode": "include", "slot": "mouth"}]},
    "sad": {"category": "PEmotion", "text": "tears"},
    "angry": {"category": "PEmotion", "text": "frown"},
    "run": {"category": "PPose", "text": "running, %PEmotion, ~smile"},
    "smile": {"category": "PFace", "text": "big smile"},
}


def with_bans(**changes):
    blocks = copy.deepcopy(BLOCKS)
    for name, value in changes.items():
        blocks[name]["bans"] = value
    return blocks


def expand(prompt, blocks, seed, **kw):
    return parser.expand(prompt, blocks, random.Random(seed), **kw)


def test_banned_block_is_kept_out_of_the_pool():
    seen = set()
    ninja_seen = 0
    for seed in range(300):
        pk, ev = [], []
        out = expand("%PCharacter, %PEmotion", BLOCKS, seed, picks=pk, ban_events=ev)
        if pk[0]["block"] == "ninja":
            ninja_seen += 1
            assert pk[1]["block"] in ("sad", "angry")
            seen.add(pk[1]["block"])
            assert "smile" not in out and out.startswith("ninja, mask, ")
            assert bans.ban_lines(ev) == ["⛔ ninja: ~happy kept out of %PEmotion"]
        else:
            assert ev == []
    assert ninja_seen > 50 and seen == {"sad", "angry"}


def test_pool_filter_keeps_the_weights_of_the_rest():
    blocks = copy.deepcopy(BLOCKS)
    blocks["sad"]["weight"] = 3
    for seed in range(200):
        rng = random.Random(seed)
        first = rng.choice(["ninja", "saber"])
        if first == "ninja":
            second = rng.choices(["angry", "sad"], weights=[1, 3], k=1)[0]
        else:
            second = rng.choices(["angry", "happy", "sad"], weights=[1, 1, 3], k=1)[0]
        pk = []
        expand("%PCharacter, %PEmotion", blocks, seed, picks=pk)
        assert [p["block"] for p in pk] == [first, second]


def test_banned_category_silences_the_token_with_clean_commas():
    blocks = with_bans(ninja=["%PEmotion"])
    for seed in range(100):
        pk, ev = [], []
        out = expand("%PCharacter, %PEmotion", blocks, seed, picks=pk, ban_events=ev)
        if pk[0]["block"] == "ninja":
            assert out == "ninja, mask"
            assert pk[1] == {"kind": "category", "category": "PEmotion", "block": None, "silenced": True}
            assert bans.ban_lines(ev) == ["⛔ ninja: %PEmotion silenced"]
    for prompt, want in (("a, %PEmotion, b, ~ninja", "a, b, ninja, mask"),
                         ("%PEmotion, a, ~ninja", "a, ninja, mask"),
                         ("~ninja,%PEmotion", "ninja, mask"),
                         ("~ninja, %PEmotion,\n%PEmotion, x", "ninja, mask, x")):
        assert expand(prompt, blocks, 0) == want


def test_every_pool_block_banned_silences_the_token():
    blocks = with_bans(ninja=["~happy", "~sad", "~angry"])
    ev = []
    assert expand("~ninja, %PEmotion", blocks, 3, ban_events=ev) == "ninja, mask"
    assert bans.ban_lines(ev) == ["⛔ ninja: %PEmotion silenced (every block of it is banned)"]


# ---------------------------------------------------------------- acceptance 3: selection pass first

def test_pose_text_is_expanded_after_the_selection_pass():
    blocks = with_bans(ninja=["%PEmotion", "~smile"])
    ninja_seen = 0
    for seed in range(200):
        pk, ev = [], []
        out = expand("%PPose, %PCharacter, %PEmotion", blocks, seed, picks=pk, ban_events=ev)
        if pk[1]["block"] == "ninja":
            ninja_seen += 1
            assert out == "running, ninja, mask"
            assert bans.ban_lines(ev) == ["⛔ ninja: %PEmotion silenced", "⛔ ninja: ~smile silenced"]
        else:
            assert "big smile" in out
    assert ninja_seen > 50


def test_nested_pool_is_filtered_by_a_pick_further_right():
    for seed in range(200):
        pk = []
        out = expand("%PPose, %PCharacter", BLOCKS, seed, picks=pk)
        if pk[1]["block"] == "ninja":
            assert "grin" not in out and out.split(", ")[1] in ("tears", "frown")


# ---------------------------------------------------------------- acceptance 4: direct calls

def test_banned_direct_calls_are_silenced_left_and_right():
    for prompt in ("~happy, ~ninja", "~ninja, ~happy", "~happy.big, ~ninja", "~ninja, ~happy*mouth"):
        ev = []
        assert expand(prompt, BLOCKS, 0, ban_events=ev) == "ninja, mask"
        token = prompt.replace("~ninja", "").strip(", ")
        assert bans.ban_lines(ev) == [f"⛔ ninja: {token} silenced"]


def test_banned_direct_call_inside_another_block_is_silenced():
    blocks = copy.deepcopy(BLOCKS)
    blocks["scene"] = {"category": "PScene", "text": "park, ~happy, day"}
    assert expand("~ninja, ~scene", blocks, 0) == "ninja, mask, park, day"
    assert expand("~scene, ~ninja", blocks, 0) == "park, day, ninja, mask"
    # Bans of a block met deeper apply to what is expanded after it (left to right).
    blocks["cast"] = {"category": "PScene", "text": "~ninja"}
    assert expand("~cast, ~happy", blocks, 0) == "ninja, mask"


def test_direct_calls_of_a_banned_category_are_silenced():
    blocks = with_bans(ninja=["%PEmotion"])
    assert expand("~ninja, ~sad, ~happy.big, x", blocks, 0) == "ninja, mask, x"


def test_the_banner_is_never_silenced_by_its_own_bans():
    blocks = with_bans(ninja=["%PCharacter", "~ninja"])
    assert expand("~ninja, ~ninja", blocks, 0) == "ninja, mask, ninja, mask"
    assert expand("~ninja, ~saber", blocks, 0) == "ninja, mask"
    # A %PCharacter token is a call of the banned category: silenced (explicit bans are active from the start).
    assert expand("%PCharacter, ~ninja", blocks, 0) == "ninja, mask"
    # Picked by its own category before any ban is active, the banner itself stays.
    blocks = with_bans(ninja=["%PCharacter"])
    for seed in range(50):
        pk = []
        out = expand("%PCharacter, ~saber", blocks, seed, picks=pk)
        if pk[0]["block"] == "ninja":
            assert out == "ninja, mask"
        else:
            assert out == "1girl, saber, 1girl, saber"


def test_mutual_explicit_bans_left_one_wins():
    blocks = copy.deepcopy(BLOCKS)
    blocks["happy"]["bans"] = ["~ninja"]
    assert expand("~ninja, ~happy", blocks, 0) == "ninja, mask"
    assert expand("~happy, ~ninja", blocks, 0) == "smile, grin, open mouth, <lora:happy:0.5>"


def test_earlier_pick_banned_by_a_later_pick_is_redrawn():
    # Step 3 replaced the step-2 interim rule (silence): happy, banned by ninja further right, is
    # redrawn from the rest of %PEmotion after the selection draws.
    hit = 0
    for seed in range(300):
        r = random.Random(seed)
        first, second = r.choice(["angry", "happy", "sad"]), r.choice(["ninja", "saber"])
        pk, ev, tr = [], [], []
        out = expand("%PEmotion, %PCharacter", BLOCKS, seed, picks=pk, ban_events=ev, trace=tr)
        if first == "happy" and second == "ninja":
            hit += 1
            want = r.choice(["angry", "sad"])
            assert [p["block"] for p in pk] == [want, "ninja"]
            assert out == BLOCKS[want]["text"] + ", ninja, mask"
            assert bans.ban_lines(ev) == [f"⛔ ninja: ~happy redrawn in %PEmotion → ~{want}"]
            assert picks.summary(pk, tr) == f"PEmotion={want}, PCharacter=ninja"
            assert picks.pin_prompt("%PEmotion, %PCharacter", pk, BLOCKS) == (f"~{want}, ~ninja", 2)
        else:
            assert [p["block"] for p in pk] == [first, second] and ev == []
    assert hit > 10


def test_silenced_slot_draw_is_recorded_as_silenced():
    pk = []
    expand("~ninja, ~happy*mouth", BLOCKS, 0, picks=pk)
    assert pk == [{"kind": "slot", "name": "happy", "slot": "mouth", "sub": None, "silenced": True}]
    assert picks.summary(pk, []) == ""


def test_whole_text_silenced_cleans_the_parent_separator():
    blocks = with_bans(ninja=["%PEmotion"])
    blocks["mood"] = {"category": "PMood", "text": "%PEmotion"}
    assert expand("a, ~mood, b, ~ninja", blocks, 0) == "a, b, ninja, mask"


@pytest.mark.parametrize("prompt, want", [
    ("~ninja, (%PEmotion:1.2), detailed", "ninja, mask, detailed"),
    ("~ninja, ( %PEmotion ), detailed", "ninja, mask, detailed"),
    ("~ninja, [%PEmotion], detailed", "ninja, mask, detailed"),
    ("~ninja, [%PEmotion:0.5], detailed", "ninja, mask, detailed"),
    ("~ninja, ((%PEmotion)), detailed", "ninja, mask, detailed"),
    ("~ninja, ([ %PEmotion , ~sad ]:1.1), detailed", "ninja, mask, detailed"),
    ("(%PEmotion:1.2), ~ninja", "ninja, mask"),
    ("~ninja, (%PEmotion, red:1.2), x", "ninja, mask, (red:1.2), x"),
    ("~ninja, ((%PEmotion), red), x", "ninja, mask, (red), x"),
    ("~ninja, (%PEmotion:1.2)", "ninja, mask"),
])
def test_silenced_token_removes_its_emptied_attention_group(prompt, want):
    blocks = with_bans(ninja=["%PEmotion"])
    assert expand(prompt, blocks, 0) == want


def test_emptied_group_across_levels_and_user_written_empty_groups_stay():
    blocks = with_bans(ninja=["%PEmotion"])
    blocks["pose"] = {"category": "PPose", "text": "standing"}
    blocks["mood"] = {"category": "PMood", "text": "(%PEmotion:1.3)"}
    blocks["mood2"] = {"category": "PMood", "text": "%PEmotion"}
    assert expand("~pose, ~ninja, (%PEmotion:1.2), detailed", blocks, 0) == "standing, ninja, mask, detailed"
    assert expand("~ninja, ~mood, x", blocks, 0) == "ninja, mask, x"
    assert expand("~ninja, (~mood2:1.2), x", blocks, 0) == "ninja, mask, x"
    # Empty groups the user wrote are kept exactly, on the ban path and on the fast path.
    assert expand("~ninja, (:1.2), ( ), [], [:0.5], %PEmotion, x", blocks, 0) == \
        "ninja, mask, (:1.2), ( ), [], [:0.5], x"
    plain = copy.deepcopy(BLOCKS)
    plain["ninja"].pop("bans")
    assert expand("~ninja, (:1.2), ( ), [], [:0.5]", plain, 0) == "ninja, mask, (:1.2), ( ), [], [:0.5]"


# ---------------------------------------------------------------- acceptance 5: no LoRA / uses / ADetailer

def test_silenced_block_adds_no_lora_no_use_no_adetailer_text():
    uses = []
    out = expand("~ninja, ~happy, %PEmotion", BLOCKS, 1, uses=uses)
    assert "<lora:happy" not in out
    assert "happy" not in [u["block"] for u in uses]
    assert adetailer.image_additions(BLOCKS, uses, 1) == [[], [], [], []]
    # Without the banner, happy is used with LoRA and ADetailer text.
    uses = []
    out = expand("~happy", BLOCKS, 1, uses=uses)
    assert "<lora:happy:0.5>" in out
    assert adetailer.image_additions(BLOCKS, uses, 1)[0] == [("happy", "happy face")]


def test_silenced_block_adds_no_bans_of_its_own():
    blocks = copy.deepcopy(BLOCKS)
    blocks["happy"]["bans"] = ["~sad"]
    # happy is silenced by ninja, so its ban on sad does not apply.
    assert expand("~ninja, ~happy, ~sad", blocks, 0) == "ninja, mask, tears"


# ---------------------------------------------------------------- negative prompts, generate, reporting

@pytest.fixture
def isolated_state(monkeypatch):
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})
    monkeypatch.setattr(state, "last_generated", {"txt2img": False, "img2img": False})


class FakeP:
    def __init__(self, prompt, negative, n=2):
        self.prompt = prompt
        self.negative_prompt = negative
        self.n_iter, self.batch_size, self.iteration = 1, n, 0
        self.extra_generation_params = {}
        self.all_prompts = [prompt] * n
        self.all_negative_prompts = [negative] * n


def test_negative_prompt_has_its_own_ban_set(isolated_state):
    lines = []
    p = FakeP("~ninja, %PEmotion", "~happy, worst quality")
    generate.process(p, "txt2img", (5, False), lambda: BLOCKS, hook_ready=lambda: False,
                     log=lambda *a: None, debug=lambda *a: lines.append(" ".join(map(str, a))))
    assert p.all_negative_prompts == ["smile, grin, open mouth, worst quality"] * 2
    assert all("smile" not in pr for pr in p.all_prompts)
    p = FakeP("x", "~ninja, ~happy")
    generate.process(p, "txt2img", (5, False), lambda: BLOCKS, hook_ready=lambda: False, log=lambda *a: None)
    assert p.all_negative_prompts == ["ninja, mask"] * 2


def test_generate_console_line_and_final_picks(isolated_state):
    lines = []
    p = FakeP("%PCharacter, %PEmotion", "~ninja, ~sad")
    blocks = with_bans(ninja=["%PEmotion"])
    seed = next(s for s in range(100) if expand("%PCharacter", blocks, s).startswith("ninja"))
    generate.process(p, "txt2img", (seed, False), lambda: blocks, hook_ready=lambda: False,
                     log=lambda *a: None, debug=lambda *a: lines.append(" ".join(map(str, a))))
    ban_lines = [ln for ln in lines if ln.startswith("bans image")]
    assert ban_lines[0] == ("bans image 0: ninja: %PEmotion silenced | negative: ninja: ~sad silenced")
    assert all(ln.isascii() for ln in ban_lines)
    value = p.extra_generation_params[generate.PICKS_INFOTEXT_KEY].value_at(0)
    assert value == "PCharacter=ninja"
    assert generate.TEMPLATE_INFOTEXT_KEY in p.extra_generation_params
    assert all("bans" not in k.lower() for k in p.extra_generation_params)


def test_ban_lines_only_when_a_ban_changed_something():
    ev = []
    # ninja is reachable (ban path) but bans nothing in this prompt.
    expand("~ninja, ~sad, %PCharacter", BLOCKS, 0, ban_events=ev)
    assert bans.ban_lines(ev) == [] and generate.ban_console_lines([ev], [[]]) == []
    ev = []
    expand("~ninja, ~happy, ~happy", BLOCKS, 0, ban_events=ev)
    assert bans.ban_lines(ev) == ["⛔ ninja: ~happy silenced"]
    assert bans.console_line(ev) == "ninja: ~happy silenced"


def test_cycle_checks_ignore_bans():
    blocks = copy.deepcopy(BLOCKS)
    blocks["loop"] = {"category": "PLoop", "text": "~loop"}
    blocks["ninja"]["text"] = "ninja, ~loop"
    blocks["ninja"]["bans"] = ["~loop"]
    # At Generate the banned loop is silenced (never expanded) ...
    assert expand("~ninja", blocks, 0) == "ninja"
    # ... but the save-time check still sees the cycle.
    with pytest.raises(parser.BlockCycleError):
        expand("~ninja", blocks, 0, apply_bans=False)
