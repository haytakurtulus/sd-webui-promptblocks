"""Block bans, step 3 (design notes section 38): the fix-up pass. A depth-0 %Category pick banned by a pick
further right is redrawn once; mutual bans: left wins; bounded and deterministic."""

import copy
import random

from pb_core import bans, generate, parser, picks, state

POSES = ["kiss_pose", "sit", "walk"]  # category_pool order (sorted by name)
CHARS = ["ninja", "saber"]

BLOCKS = {
    "kiss_pose": {"category": "PPose", "text": "kissing"},
    "sit": {"category": "PPose", "text": "sitting"},
    "walk": {"category": "PPose", "text": "walking"},
    "ninja": {"category": "PCharacter", "text": "ninja, mask", "bans": ["~kiss_pose"]},
    "saber": {"category": "PCharacter", "text": "1girl, saber"},
    "calm": {"category": "PEmotion", "text": "calm"},
}


def with_changes(**changes):
    blocks = copy.deepcopy(BLOCKS)
    for name, fields in changes.items():
        blocks.setdefault(name, {}).update(fields)
    return blocks


def expand(prompt, blocks, seed, **kw):
    return parser.expand(prompt, blocks, random.Random(seed), **kw)


def _redraw_seeds(n=400):
    # Seeds whose selection pass draws kiss_pose, then ninja (equal weights -> rng.choice each).
    found = []
    for seed in range(n):
        r = random.Random(seed)
        if r.choice(POSES) == "kiss_pose" and r.choice(CHARS) == "ninja":
            found.append(seed)
    return found


def _expected_redraw(seed):
    r = random.Random(seed)
    r.choice(POSES)
    r.choice(CHARS)
    return r, r.choice(["sit", "walk"])  # the redraw: after both selection draws, pool minus the ban


# ---------------------------------------------------------------- acceptance 1: redraw, never silenced

def test_banned_earlier_pick_is_redrawn_from_the_rest():
    seeds = _redraw_seeds()
    assert len(seeds) > 20
    got = set()
    for seed in seeds:
        _, want = _expected_redraw(seed)
        got.add(want)
        pk, ev, tr = [], [], []
        out = expand("%PPose, %PCharacter", BLOCKS, seed, picks=pk, ban_events=ev, trace=tr)
        assert [p["block"] for p in pk] == [want, "ninja"]
        assert not any(p.get("silenced") for p in pk)
        assert out == BLOCKS[want]["text"] + ", ninja, mask"
        assert bans.ban_lines(ev) == [f"⛔ ninja: ~kiss_pose redrawn in %PPose → ~{want}"]
        # Picks / Pin show the final pick.
        assert picks.summary(pk, tr) == f"PPose={want}, PCharacter=ninja"
        assert picks.pin_prompt("%PPose, %PCharacter", pk, BLOCKS) == (f"~{want}, ~ninja", 2)
    assert got == {"sit", "walk"}


def test_never_silenced_when_another_pose_exists():
    ninja = 0
    for seed in range(300):
        pk = []
        out = expand("%PPose, %PCharacter", BLOCKS, seed, picks=pk)
        if pk[1]["block"] == "ninja":
            ninja += 1
            assert pk[0]["block"] in ("sit", "walk") and "kissing" not in out
    assert ninja > 100


def test_redraw_keeps_the_weights_of_the_rest():
    blocks = with_changes(walk={"weight": 3})
    seen = 0
    for seed in range(400):
        r = random.Random(seed)
        first = r.choices(POSES, weights=[1, 1, 3], k=1)[0]
        second = r.choice(CHARS)
        if not (first == "kiss_pose" and second == "ninja"):
            continue
        seen += 1
        want = r.choices(["sit", "walk"], weights=[1, 3], k=1)[0]
        pk = []
        expand("%PPose, %PCharacter", blocks, seed, picks=pk)
        assert pk[0]["block"] == want
    assert seen > 10


def test_redraw_with_an_empty_pool_silences_the_token():
    blocks = {"kiss_pose": BLOCKS["kiss_pose"], "ninja": BLOCKS["ninja"]}
    ev, pk = [], []
    assert expand("%PPose, %PCharacter", blocks, 0, picks=pk, ban_events=ev) == "ninja, mask"
    assert pk[0] == {"kind": "category", "category": "PPose", "block": None, "silenced": True}
    assert bans.ban_lines(ev) == ["⛔ ninja: %PPose silenced (every block of it is banned)"]


def test_rng_order_redraw_after_selection_before_expansion():
    blocks = with_changes(sit={"text": "sitting, %PMood"}, walk={"text": "walking, %PMood"},
                          m1={"category": "PMood", "text": "m1"}, m2={"category": "PMood", "text": "m2"})
    for seed in _redraw_seeds():
        r, pose = _expected_redraw(seed)
        mood = r.choice(["m1", "m2"])  # the nested draw comes after the redraw
        text = "sitting" if pose == "sit" else "walking"
        assert expand("%PPose, %PCharacter", blocks, seed) == f"{text}, {mood}, ninja, mask"


def test_console_line_and_picks_infotext_show_the_redraw(monkeypatch):
    monkeypatch.setattr(state, "last_picks", {"txt2img": [], "img2img": []})
    monkeypatch.setattr(state, "last_generated", {"txt2img": False, "img2img": False})

    class P:
        prompt = "%PPose, %PCharacter"
        negative_prompt = ""
        n_iter, batch_size, iteration = 1, 1, 0

        def __init__(self):
            self.extra_generation_params = {}
            self.all_prompts = [self.prompt]
            self.all_negative_prompts = [""]

    seed = _redraw_seeds()[0]
    _, want = _expected_redraw(seed)
    lines, p = [], P()
    generate.process(p, "txt2img", (seed, False), lambda: BLOCKS, hook_ready=lambda: False,
                     log=lambda *a: None, debug=lambda *a: lines.append(" ".join(map(str, a))))
    ban = [ln for ln in lines if ln.startswith("bans image")]
    assert ban == [f"bans image 0: ninja: ~kiss_pose redrawn in %PPose -> ~{want}"]
    assert p.extra_generation_params[generate.PICKS_INFOTEXT_KEY].value_at(0) == (
        f"PPose={want}, PCharacter=ninja")
    assert p.all_prompts == [BLOCKS[want]["text"] + ", ninja, mask"]


# ---------------------------------------------------------------- acceptance 2: mutual bans, left wins

def test_mutual_ban_pose_left_stays_and_character_never_ninja():
    blocks = with_changes(kiss_pose={"bans": ["~ninja"]})
    kiss = 0
    for seed in range(300):
        pk = []
        out = expand("%PPose, %PCharacter", blocks, seed, picks=pk)
        if pk[0]["block"] == "kiss_pose":
            kiss += 1
            assert pk[1]["block"] == "saber" and out == "kissing, 1girl, saber"
        if pk[1]["block"] == "ninja":
            assert pk[0]["block"] != "kiss_pose"
    assert kiss > 50


def test_mutual_ban_every_character_banned_silences_the_character():
    blocks = with_changes(kiss_pose={"bans": ["~ninja", "~saber"]})
    kiss = 0
    for seed in range(100):
        pk = []
        out = expand("%PPose, %PCharacter", blocks, seed, picks=pk)
        if pk[0]["block"] == "kiss_pose":
            kiss += 1
            assert out == "kissing" and pk[1]["silenced"]
    assert kiss > 10


def test_mutual_ban_through_categories_left_wins():
    blocks = with_changes(ninja={"bans": ["%PPose"]}, kiss_pose={"bans": ["%PCharacter"]})
    for seed in range(100):
        pk = []
        out = expand("%PPose, %PCharacter", blocks, seed, picks=pk)
        if pk[0].get("block") == "kiss_pose":
            assert out == "kissing" and pk[1]["silenced"]
        elif pk[1].get("block") == "ninja":
            # ninja bans the whole %PPose: no redraw possible -> the pose is silenced.
            assert out == "ninja, mask" and pk[0]["silenced"]


def _state(blocks, selected):
    ban = bans.BanState([])
    for key, name in selected.items():
        ban.selected[key] = name
        ban.add(name, blocks[name])
    order = [[key, blocks[name]["category"], parser.category_pool(blocks, blocks[name]["category"])]
             for key, name in sorted(selected.items())]
    return ban, order


def test_fix_up_mutual_redraws_the_later_pick():
    # The selection pass never lets an earlier pick ban a later one (the earlier pick's bans already
    # filter the later pool), so the fix-up's mutual branch is exercised with a hand-made selection.
    blocks = with_changes(kiss_pose={"bans": ["~ninja"]})
    ban, order = _state(blocks, {0: "kiss_pose", 11: "ninja"})
    parser._fix_up(order, blocks, random.Random(0), None, ban)
    assert ban.selected == {0: "kiss_pose", 11: "saber"}
    assert bans.ban_lines(ban.events) == [
        "⛔ ~kiss_pose and ~ninja ban each other: ~ninja redrawn in %PCharacter → ~saber (first in prompt wins)"]
    blocks = with_changes(kiss_pose={"bans": ["~ninja", "~saber"]})
    ban, order = _state(blocks, {0: "kiss_pose", 11: "ninja"})
    parser._fix_up(order, blocks, random.Random(0), None, ban)
    assert ban.selected == {0: "kiss_pose", 11: None}
    assert bans.ban_lines(ban.events) == ["⛔ kiss_pose: %PCharacter silenced (every block of it is banned)"]


def test_fix_up_mutual_and_plain_banner_redraws_the_earlier_pick():
    blocks = with_changes(kiss_pose={"bans": ["~ninja"]}, calm={"bans": ["~kiss_pose"]})
    ban, order = _state(blocks, {0: "kiss_pose", 11: "ninja", 25: "calm"})
    parser._fix_up(order, blocks, random.Random(0), None, ban)
    assert ban.selected[0] in ("sit", "walk") and ban.selected[11] == "ninja" and ban.selected[25] == "calm"


# ---------------------------------------------------------------- acceptance 3: all active bans

def test_redraw_honours_bans_of_explicit_calls():
    blocks = with_changes(kiri={"category": "PExtra", "text": "kiri", "bans": ["~sit"]})
    ninja = 0
    for seed in range(200):
        pk = []
        out = expand("%PPose, %PCharacter, ~kiri", blocks, seed, picks=pk)
        assert pk[0]["block"] != "sit"
        if pk[1]["block"] == "ninja":
            ninja += 1
            assert pk[0]["block"] == "walk" and out == "walking, ninja, mask, kiri"
    assert ninja > 50


def test_redraw_honours_bans_of_other_picks():
    blocks = with_changes(calm={"bans": ["~walk"]})
    hit = 0
    for seed in range(400):
        pk, ev = [], []
        expand("%PPose, %PCharacter, %PEmotion", blocks, seed, picks=pk, ban_events=ev)
        if pk[1]["block"] == "ninja":
            assert pk[0]["block"] == "sit"
            if "⛔ ninja: ~kiss_pose redrawn in %PPose → ~sit" in bans.ban_lines(ev):
                hit += 1
    assert hit > 5


def test_redraw_honours_a_category_ban_by_silencing():
    blocks = with_changes(calm={"bans": ["%PPose"]})
    ev, pk = [], []
    assert expand("%PPose, %PEmotion", blocks, 0, picks=pk, ban_events=ev) == "calm"
    assert pk[0]["silenced"] and bans.ban_lines(ev) == ["⛔ calm: %PPose silenced"]


# ---------------------------------------------------------------- acceptance 4: bounded, deterministic

def test_chain_redrawn_pick_bans_a_pick_further_right_which_is_silenced():
    # x1 is banned by z1 (right) -> redrawn to x2; x2 bans z1: no further redraw, z1 is silenced at the
    # expansion (a redrawn pick's bans apply to what is expanded after it).
    blocks = {"x1": {"category": "X", "text": "x1"}, "x2": {"category": "X", "text": "x2", "bans": ["~z1"]},
              "z1": {"category": "Z", "text": "z1", "bans": ["~x1"]}}
    hit = 0
    for seed in range(50):
        pk, ev = [], []
        out = expand("%X, %Z", blocks, seed, picks=pk, ban_events=ev)
        if random.Random(seed).choice(["x1", "x2"]) == "x1":
            hit += 1
            assert out == "x2" and pk[0]["block"] == "x2" and pk[1]["silenced"]
            assert bans.ban_lines(ev) == ["⛔ z1: ~x1 redrawn in %X → ~x2", "⛔ x2: ~z1 (picked by %Z) silenced"]
        else:
            # x2 picked first: its bans keep z1 out of %Z, which is then empty.
            assert out == "x2" and pk[1]["silenced"]
    assert hit > 10


def test_chain_redrawn_pick_never_affects_a_pick_to_its_left():
    # w1 | x1 banned by y1 -> redrawn to x2, x2 bans w1 (left): w1 stays (left wins), no loop.
    blocks = {"w1": {"category": "W", "text": "w1"},
              "x1": {"category": "X", "text": "x1"}, "x2": {"category": "X", "text": "x2", "bans": ["~w1"]},
              "y1": {"category": "Y", "text": "y1", "bans": ["~x1"]}}
    hit = 0
    for seed in range(50):
        r = random.Random(seed)
        r.choice(["w1"])
        if r.choice(["x1", "x2"]) == "x1":
            hit += 1
            assert expand("%W, %X, %Y", blocks, seed) == "w1, x2, y1"
        else:
            # x2 drawn by the selection pass is an ordinary banner further right: w1 is redrawn, its
            # pool (only w1) is empty -> silenced.
            assert expand("%W, %X, %Y", blocks, seed) == "x2, y1"
    assert hit > 10


def test_chain_a_bans_b_redraw_c_bans_a_finishes():
    # A bans B; the redraw of B gives C; C bans A.
    blocks = {"b": {"category": "K1", "text": "b"}, "c": {"category": "K1", "text": "c", "bans": ["~a"]},
              "a": {"category": "K2", "text": "a", "bans": ["~b"]},
              "a2": {"category": "K2", "text": "a2"}}
    outputs = set()
    for seed in range(100):
        pk, ev = [], []
        out = expand("%K1, %K2, %K1", blocks, seed, picks=pk, ban_events=ev)
        assert out == expand("%K1, %K2, %K1", blocks, seed)
        assert sum(1 for e in ev if e["kind"] == "redrawn") <= 3
        outputs.add(out)
    assert len(outputs) > 1


def test_random_ban_graphs_terminate_and_are_deterministic():
    r = random.Random(7)
    cats = ["C0", "C1", "C2", "C3"]
    redraws = 0
    for _ in range(150):
        blocks = {}
        for i in range(10):
            b = {"category": cats[i % 4], "text": f"t{i}"}
            if r.random() < 0.6:
                b["bans"] = sorted({r.choice([f"~n{r.randrange(10)}", "%" + r.choice(cats)])
                                    for _ in range(r.randint(1, 3))})
            if r.random() < 0.2:
                b["weight"] = r.choice([0.5, 2])
            blocks[f"n{i}"] = b
        prompt = ", ".join(r.choice(["%" + c for c in cats] + [f"~n{r.randrange(10)}"])
                           for _ in range(r.randint(2, 6)))
        for seed in range(10):
            rng, rng2 = random.Random(seed), random.Random(seed)
            pk, ev, pk2, ev2 = [], [], [], []
            out = parser.expand(prompt, blocks, rng, picks=pk, ban_events=ev)
            assert parser.expand(prompt, blocks, rng2, picks=pk2, ban_events=ev2) == out
            assert pk == pk2 and ev == ev2 and rng.getstate() == rng2.getstate()
            n_cat = sum(1 for p in pk if p["kind"] == "category")
            n_redraw = sum(1 for e in ev if e["kind"] == "redrawn")
            assert n_redraw <= n_cat
            redraws += n_redraw
    assert redraws > 20
