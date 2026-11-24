import os
import random
import sys
from typing import Optional

import gradio as gr
from fastapi import HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from modules import scripts, script_callbacks, shared

EXT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EXT_ROOT not in sys.path:
    sys.path.insert(0, EXT_ROOT)

from pb_core import adetailer, bans, create, generate, parser, picks, state, storage, subrows, ui, weights

DEBUG_OPTION = "promptblocks_debug"
SEED_INFOTEXT_KEY = generate.SEED_INFOTEXT_KEY
TABS = ("txt2img", "img2img")

# First start (design notes section 41): copy the example blocks when there is no blocks.json yet.
# seed_starter_blocks() never raises; the extra guard keeps the extension loading whatever happens.
try:
    storage.seed_starter_blocks()
except Exception:
    pass


def debug(*args):
    if getattr(shared.opts, DEBUG_OPTION, False):
        print("[PromptBlocks]", *args)


def console(line):
    # Console output must stay ASCII (Windows console encoding).
    print(str(line).encode("ascii", "backslashreplace").decode("ascii"))


def adetailer_runners(p):
    # ScriptRunners that may hold ADetailer's script instance (section 31a): the module-level txt2img /
    # img2img runners and the one of this generation.
    return [getattr(p, "scripts", None), getattr(scripts, "scripts_txt2img", None),
            getattr(scripts, "scripts_img2img", None)]


class PromptBlocksScript(scripts.Script):
    def title(self):
        return "PromptBlocks"

    def show(self, is_img2img):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        tab = "img2img" if is_img2img else "txt2img"
        with gr.Accordion("PromptBlocks", open=False):
            block_seed = gr.Number(
                label="Block seed (-1 = random on every Generate)",
                value=-1,
                precision=0,
                elem_id=f"pb_block_seed_{tab}",
            )
            gr.HTML(
                # .pb-acc wrapper: lets style.css out-rank Gradio's own input / button / .prose rules
                # (design notes 23b).
                f'<div class="pb-acc">'
                f'<div id="pb_preview_{tab}" class="pb-preview">Type a prompt to see an example.</div>'
                f'<button id="pb_reroll_{tab}" class="pb-reroll" type="button">Another example</button>'
                f'<button id="pb_pin_{tab}" class="pb-reroll pb-pin" type="button"'
                f' title="Replace %Category / ~name*slot in the prompt with what the last Generate picked">'
                f'Pin last picks</button>'
                # Own line for Pin messages: the preview box is rewritten by every preview refresh.
                f'<div id="pb_pin_msg_{tab}" class="pb-create-msg pb-pin-msg"></div>'
                # Section 16: save the selected prompt text as a new block.
                f'<div id="pb_create_row_{tab}" class="pb-create">'
                f'<input id="pb_new_name_{tab}" class="pb-create-input" type="text" placeholder="New block name"'
                f' autocomplete="off" spellcheck="false">'
                f'<input id="pb_new_cat_{tab}" class="pb-create-input" type="text" placeholder="Category"'
                f' list="pb_cats_{tab}" autocomplete="off" spellcheck="false">'
                f'<datalist id="pb_cats_{tab}"></datalist>'
                f'<button id="pb_create_{tab}" class="pb-reroll pb-create-btn" type="button"'
                f' title="Save the selected prompt text as a new block and replace it with ~name">'
                f'Save selection as block</button>'
                f'</div>'
                f'<div id="pb_create_msg_{tab}" class="pb-create-msg"></div>'
                f'</div>'
            )
            # Section 31a: append the used blocks' ADetailer texts to ADetailer's own prompts.
            add_adetailer = gr.Checkbox(label="Add ADetailer text", value=True,
                                        elem_id=f"pb_add_adetailer_{tab}")
            # Section 35: ADetailer gets the main prompt's LoRA tags (no LoRA re-merge between passes).
            keep_loras = gr.Checkbox(
                label="Keep main LoRAs in ADetailer", value=True,
                info="ADetailer gets the main prompt's LoRA tags (same order and weights) instead of its own:"
                     " no LoRA reload, less RAM. Face-only LoRAs written in ADetailer are replaced.",
                elem_id=f"pb_keep_loras_adetailer_{tab}")
        self.infotext_fields = [(block_seed, SEED_INFOTEXT_KEY)]
        self.paste_field_names = [SEED_INFOTEXT_KEY]
        # New args only at the END (older API calls / infotext without them -> defaults in generate.process).
        return [block_seed, add_adetailer, keep_loras]

    def process(self, p, *args):
        tab = "img2img" if self.is_img2img else "txt2img"
        # pb_core.generate holds the whole step (testable); it skips a p it already handled (section 33 A).
        generate.process(p, tab, args, storage.load_blocks,
                         hook_ready=lambda: adetailer.install_all(adetailer_runners(p), warn=console),
                         log=console, debug=debug)

    def postprocess_image(self, p, pp, *args):
        state.last_image = pp.image.copy()


class PreviewRequest(BaseModel):
    prompt: str
    seed: Optional[int] = None


class PinRequest(BaseModel):
    prompt: str
    tab: str = "txt2img"


class CreateRequest(BaseModel):
    name: str = ""
    category: str = ""
    text: str = ""


def on_app_started(demo, app):
    @app.get("/promptblocks/blocks")
    def get_blocks():
        blocks = storage.load_blocks()
        return {
            "block_symbol": parser.BLOCK_SYMBOL,
            "category_symbol": parser.CATEGORY_SYMBOL,
            "name_pattern": parser.NAME_PATTERN,
            "sub_separator": parser.SUB_SEPARATOR,
            "slot_draw_separator": parser.SLOT_DRAW_SEPARATOR,
            "blocks": {
                n: {**b, "active": weights.is_active(b), "thumb_v": storage.thumb_mtime(n),
                    **subrows.api_block_slots(b), **subrows.api_block_lora(b)}
                for n, b in blocks.items()
                if isinstance(b, dict)  # broken hand-edited entries are not offered in the popup
            },
        }

    @app.get("/promptblocks/thumb/{name}")
    def get_thumb(name: str):
        if not parser.is_valid_name(name):
            raise HTTPException(status_code=404)
        path = storage.thumb_path(name)
        if not os.path.exists(path):
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="image/webp")

    @app.post("/promptblocks/preview")
    def preview(req: PreviewRequest):
        from_field = req.seed is not None and req.seed >= 0
        seed = req.seed if from_field else random.randrange(2**32)
        blocks = storage.load_blocks()
        trace, uses, ban_events = [], [], []
        try:
            text = parser.expand(req.prompt, blocks, random.Random(seed), trace=trace, uses=uses,
                                 ban_events=ban_events)
        except parser.BlockCycleError as e:
            return {"error": str(e)}
        unknown, all_inactive = parser.preview_warnings(text, blocks)
        # Section 31a: ADetailer additions of the first image (its block seed is `seed`).
        # Section 38 step 4: resolved under the image's ban set, like at Generate.
        ad_errors, ad_ban_events = [], []
        additions = adetailer.image_additions(blocks, uses, seed, ad_errors, ban_events=ad_ban_events)
        unknown, all_inactive = adetailer.preview_warnings(additions, blocks, unknown, all_inactive)
        return {
            "text": text,
            "seed": seed,
            "from_field": from_field,
            "unknown": unknown,
            "all_inactive": all_inactive,
            "subs_picked": subrows.api_trace(trace),
            "occupied_slots": sorted(parser.occupied_slots(req.prompt, blocks)),
            "adetailer": {"tabs": adetailer.preview_entries(additions), "errors": ad_errors},
            # Section 38: one line per ban effect ([] when no ban changed anything).
            "bans": bans.ban_lines(ban_events) + adetailer.preview_ban_lines(ad_ban_events),
        }

    @app.post("/promptblocks/pin")
    def pin(req: PinRequest):
        # Section 15: replace the random depth-0 tokens of the given prompt with the picks of the first
        # image of the last generation in that tab.
        stored = state.last_picks.get(req.tab, []) if req.tab in TABS else []
        generated = state.last_generated.get(req.tab, False) if req.tab in TABS else False
        return picks.pin_response(req.prompt, stored, storage.load_blocks(), generated)

    @app.post("/promptblocks/create")
    def create_block(req: CreateRequest):
        # Section 16: new block from the selected prompt text; existing names are refused.
        new_blocks, err = create.build_new_block(storage.load_blocks(), req.name, req.category, req.text)
        if err:
            return {"ok": False, "error": err}
        storage.save_blocks(new_blocks)  # backs up the previous file (section 12)
        name = req.name.strip()
        debug("created block  =", name)
        return {"ok": True, "name": name, "token": parser.BLOCK_SYMBOL + name}


def on_ui_settings():
    section = ("promptblocks", "PromptBlocks")
    shared.opts.add_option(
        DEBUG_OPTION,
        shared.OptionInfo(False, "Print debug info to console", section=section),
    )


def on_ui_tabs():
    return [(ui.build_tab(), "PromptBlocks", "promptblocks_tab")]


script_callbacks.on_app_started(on_app_started)
script_callbacks.on_ui_settings(on_ui_settings)
script_callbacks.on_ui_tabs(on_ui_tabs)