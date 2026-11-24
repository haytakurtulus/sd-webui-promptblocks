"""PromptBlocks management tab (Gradio). Entry point: build_tab().

Where things are:
  layout.py     every component, in DOM order (Components: one key per component)
  groups.py     the input / output key lists of every listener (named once, reused)
  wiring.py     every .click / .input / .change / .then, with the shared concurrency group
  form.py       form load, block switch (tile / dropdown / New), Reload, Save
  fields.py     in-form reactions that save nothing (row moves, thumbnail, hint and chance lines)
  sidebar.py    block browser: search / filter, Enable shown / Disable shown
  tools.py      "More actions": Duplicate, Rename, Delete, Rename category, Restore, LoRA moves, Health
  refresh.py    list / choices refreshes after saved data changed
  common.py     queue settings, form signal / generation counters, out(), small shared helpers
  help_text.py  the "How it works" text

Data flow: layout.build() returns the components; handlers are plain functions that only see values
and return values in the order of a groups.py list (common.out() fills "only these outputs" responses
by key); wiring.wire() connects the two via Components.pick(keys).
"""
import gradio as gr

from . import layout, wiring


def build_tab():
    with gr.Blocks(analytics_enabled=False) as tab:
        c = layout.build()
        wiring.wire(c)
    return tab
