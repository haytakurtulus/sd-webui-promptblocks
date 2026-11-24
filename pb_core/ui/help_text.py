"""Text of the tab's "How it works" accordion."""
from ..subs import MAX_SUBS, NEW_ROW_MODE

CHEAT_SHEET = f"""\
**In the prompt**
- `~name` inserts a block's text (plus its sub-blocks and its LoRA).
- `%Category` inserts one random active block of that category.
- `~name.sub` inserts only that sub-block's text. `~name*slot` inserts one random sub-block from that slot.

**Sub-block modes** (added after the block text, in row order; up to {MAX_SUBS} sub-blocks per block)
- **Include**: always added. **Exclude**: only via `~name.sub`. **Random**: added 50% of the time by default.
- **%** column: the chance of a Random sub-block in percent (1–100, default 50); ignored for Include / Exclude.
- A new row starts as {NEW_ROW_MODE.capitalize()}. *All Include* / *All Exclude* / *All Random* (top of
  *Sub-blocks*) set the mode of every filled row of the open form (press Save to keep it). *Set sub-blocks of shown blocks*
  (under *More actions*) sets the mode of every sub-block of the blocks listed in the browser (asks first).
- An Exclude row is shown dimmed; the % box is dimmed unless the row is Random.

**Slots** (e.g. `outfit`): of one block's sub-blocks sharing a slot, at most one is added (picked randomly).
If the prompt itself calls something in that slot (`~name.sub`, `~name*slot`, or a block whose own
*Slot (block)* is set), automatically added sub-blocks in that slot are skipped
(a block's own `~name` call does not skip its own sub-blocks).

**LoRA**: added once whenever this block or one of its sub-blocks is used.

**ADetailer** (tabs 1st–4th): whenever this block is used in an image, its text for tab *k* is added to
ADetailer's own prompt of tab *k* (to every `[SEP]` part; an empty ADetailer prompt means the main
prompt). `%Category` in it gives the same block as the main prompt picked. No block LoRA is added there.
Switch it off with *Add ADetailer text* in the PromptBlocks accordion.

**Random pick settings**: Weight = relative chance in `%Category` picks (1 = normal);
inactive blocks are left out of `%Category` picks (`~name` still works).
**Bans** (also there): blocks (`~name`) or whole categories (`%Category`) that must not be used in a
prompt together with this block, comma separated, e.g. `~happy, %PEmotion`. When this block is used, a
banned block is left out of `%Category` picks (another block of the category is picked), and banned calls
(`~happy`, `%PEmotion`, `~happy.sub`, a block of a banned category) give nothing. A block is never banned
by its own bans. The preview lists what a ban changed (⛔ lines). A banned block adds no LoRA and no
ADetailer text.

**Saving**: Save (top, or the floating button at the bottom right) or **Ctrl+S** / **Ctrl+Enter** inside
this tab. Opening another block (tile or dropdown) or pressing *New* first saves a modified form; a form
that cannot be saved (e.g. empty Text) stays open with the error. *Reload* discards the changes and shows
the saved version again. A changed Name saves a new block (the original stays). *New* clears the form;
*Duplicate* (under *More actions*) keeps the form under a new name. Rename / Delete act on the block
selected in the *Block* dropdown.

**Browser** (left): filter by category (the counts show blocks, and active blocks when some are off),
click a tile to open that block. **Search** looks into the name and the content (text, LoRA, slot,
sub-block names / texts / slots, ADetailer texts, bans); several words must all be found; name matches
come first. Quick filters in the search box, combinable with words: `:off` (or `:inactive`), `:on`
(or `:active`), `:thumb`, `:nothumb`, `:bans`, `:subs`, `:lora`, `:ad` (has ADetailer text).
Tiles marked *(off)* are inactive blocks (shown dimmed); hover a tile for a summary of the block.
*Enable shown* / *Disable shown* and *Set sub-blocks of shown blocks* act on every block listed in the
browser, i.e. on what the current search + category filter shows (content matches included).
"""
