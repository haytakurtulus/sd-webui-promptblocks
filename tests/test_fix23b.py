# Design notes 23b: /promptblocks/pin response with the "generated" flag, and the per-tab state.
from pb_core import picks, state

BLOCKS = {
    "saber": {"category": "PCharacter", "text": "saber"},
    "rin": {"category": "PCharacter", "text": "rin"},
}


def test_state_has_generated_flag_per_tab_default_false():
    assert state.last_generated == {"txt2img": False, "img2img": False}


def test_pin_response_not_generated_yet():
    r = picks.pin_response("%PCharacter", [], BLOCKS, False)
    assert r == {"prompt": "%PCharacter", "replaced": 0, "available": 0, "generated": False}


def test_pin_response_generated_without_random_picks():
    r = picks.pin_response("%PCharacter", [], BLOCKS, True)
    assert r == {"prompt": "%PCharacter", "replaced": 0, "available": 0, "generated": True}


def test_pin_response_replaces_and_counts():
    stored = [{"kind": "category", "category": "PCharacter", "block": "rin"}]
    r = picks.pin_response("a, %PCharacter", stored, BLOCKS, True)
    assert r == {"prompt": "a, ~rin", "replaced": 1, "available": 1, "generated": True}


def test_pin_response_nothing_to_pin_in_prompt():
    stored = [{"kind": "category", "category": "PCharacter", "block": "rin"}]
    r = picks.pin_response("no tokens here", stored, BLOCKS, True)
    assert r["replaced"] == 0 and r["available"] == 1 and r["prompt"] == "no tokens here"


def test_pin_response_tolerates_none_and_truthy_flag():
    r = picks.pin_response("%PCharacter", None, BLOCKS, 1)
    assert r["available"] == 0 and r["generated"] is True and r["replaced"] == 0
