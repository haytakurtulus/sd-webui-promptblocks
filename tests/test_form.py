"""Form helpers of the management tab redesign (design notes section 11): blank_form ("New"),
block_form (picking a block), form_values (flat component values)."""

from pb_core import lora, subrows, subs


N = subrows.ROW_COUNT

BLOCKS = {
    "saber": {"category": "PCharacter", "text": "1girl, saber", "lora": "  <lora:saber:0.8>  ",
              "weight": 3, "slot": "hero",
              "subs": [{"name": "armor", "text": "ARMOR", "mode": "include", "slot": "outfit"},
                       {"name": "dress", "text": "DRESS", "mode": "random", "slot": None}]},
    "rin": {"category": "PCharacter", "text": "rin", "active": False},
}


def test_blank_form_defaults():
    f = subrows.blank_form()
    assert f["name"] == "" and f["category"] is None and f["block_slot"] is None
    assert f["weight"] == 1 and f["active"] is True
    assert f["chance"] == "" and f["text"] == "" and f["lora"] == ""
    assert f["rows"] == [subrows.empty_row() for _ in range(N)]


def test_blank_form_rows_are_independent_copies():
    f = subrows.blank_form()
    f["rows"][0]["name"] = "x"
    assert f["rows"][1]["name"] == ""
    assert subrows.blank_form()["rows"][0]["name"] == ""


def test_form_values_of_blank_form_layout():
    values = subrows.form_values(subrows.blank_form())
    nf = len(subrows.FORM_FIELDS)
    assert len(values) == nf + 4 * N + 1
    assert values[:nf] == ["", None, None, 1, True, "", "", ""] + [""] * 4 + [""]  # + ADetailer texts (31a), bans (38)
    rows = values[nf:]
    assert rows[:N] == [""] * N                      # names
    assert rows[N:2 * N] == [""] * N                 # texts
    assert rows[2 * N:3 * N] == [subs.NEW_ROW_MODE] * N   # blank rows start as NEW_ROW_MODE (36 A, 37 A)
    assert rows[3 * N:4 * N] == [None] * N           # slots
    assert rows[-1] == [{"orig": None}] * N          # identity meta: all rows new


def test_form_values_round_trip_rows():
    f = subrows.block_form(BLOCKS, "saber")
    values = subrows.form_values(f)
    rows = subrows.rows_from_values(values[len(subrows.FORM_FIELDS):])
    assert rows == f["rows"]


def test_block_form_loads_all_fields():
    f = subrows.block_form(BLOCKS, "saber")
    assert f["name"] == "saber" and f["category"] == "PCharacter"
    assert f["block_slot"] == "hero" and f["weight"] == 3 and f["active"] is True
    assert f["text"] == "1girl, saber"
    assert f["lora"] == "<lora:saber:0.8>"            # normalised (stripped)
    assert f["chance"]                                 # chance line present for a categorised block
    assert [r["name"] for r in f["rows"]] == ["armor", "dress"] + [""] * (N - 2)
    assert [r["orig"] for r in f["rows"]] == ["armor", "dress"] + [None] * (N - 2)
    assert f["rows"][0]["slot"] == "outfit"


def test_block_form_inactive_and_no_lora():
    f = subrows.block_form(BLOCKS, "rin")
    assert f["active"] is False and f["lora"] == "" and f["block_slot"] is None and f["weight"] == 1


def test_block_form_broken_lora_is_empty():
    f = subrows.block_form({"x": {"category": "C", "text": "t", "lora": 5}}, "x")
    assert f["lora"] == ""


def test_block_form_missing_gives_blank():
    blank = subrows.blank_form()
    assert subrows.block_form(BLOCKS, None) == blank
    assert subrows.block_form(BLOCKS, "nope") == blank
    assert subrows.block_form({"x": {}}, "x") == blank
    assert subrows.block_form({"x": "broken"}, "x") == blank
    assert subrows.block_form(None, "x") == blank


def test_lora_form_value_save_round_trip():
    # What on_save does with the LoRA box: set_block_lora on the stored block; empty removes the key.
    stored = dict(BLOCKS["saber"])
    saved = lora.set_block_lora(stored, " <lora:new:0.5> ")
    assert subrows.block_form({"saber": saved}, "saber")["lora"] == "<lora:new:0.5>"
    cleared = lora.set_block_lora(saved, "")
    assert "lora" not in cleared
    assert subrows.block_form({"saber": cleared}, "saber")["lora"] == ""
