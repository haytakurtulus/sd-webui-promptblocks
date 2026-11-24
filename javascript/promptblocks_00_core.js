// PromptBlocks shared core: the namespace, the shared state object and the block data (/promptblocks/blocks).
//
// The extension's JS is split into plain scripts that share ONE namespace, window.PromptBlocks
// (design notes section 29). Forge loads the files of one extension in filename order
// (modules/extensions.py Extension.list_files: sorted(os.listdir(...))), so the number prefixes fix the
// order: 00_core -> 10_popup -> 20_accordion -> 30_tab -> 90_boot. Each file checks that what it needs
// is already there and logs one clear console error instead of initialising half.
(() => {
    const PB = window.PromptBlocks = window.PromptBlocks || {};

    function pbEscape(s) {
        return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }

    const pb = {
        data: null, tokenRe: null, subRe: null, slotRe: null, popup: null,
        ta: null, items: [], index: 0, match: null, suppress: false,
        // dataKey: JSON text of the last /promptblocks/blocks response; builtKey: the dataKey the open
        // popup's list was built from (design notes 23b: rebuild when a refetch brings different data).
        dataKey: null, builtKey: null,
    };

    async function loadData() {
        try {
            const res = await fetch("/promptblocks/blocks");
            const text = await res.text();
            pb.data = JSON.parse(text);
            pb.dataKey = text;
        } catch (err) {
            console.error("[PromptBlocks] could not load blocks:", err);
            return false;
        }
        const B = pbEscape(pb.data.block_symbol);
        const C = pbEscape(pb.data.category_symbol);
        const S = pbEscape(pb.data.sub_separator || ".");
        pb.tokenRe = new RegExp(`(${B}|${C})(${pb.data.name_pattern})?$`);
        // ~block. or ~block.partial -> list that block's sub-blocks.
        pb.subRe = new RegExp(`(${B})(${pb.data.name_pattern})${S}(${pb.data.name_pattern})?$`);
        // ~block* or ~block*partial -> list that block's sub-block slots (slot draw).
        const D = pbEscape(pb.data.slot_draw_separator || "*");
        pb.slotRe = new RegExp(`(${B})(${pb.data.name_pattern})${D}(${pb.data.name_pattern})?$`);
        refreshCategoryLists();
        return true;
    }

    // At most one /promptblocks/blocks request at a time: a second caller shares the running one.
    let dataInFlight = null;

    function refetchData() {
        if (!dataInFlight) dataInFlight = loadData().finally(() => { dataInFlight = null; });
        return dataInFlight;
    }

    // For callers that changed the data themselves (e.g. /promptblocks/create): a request that is
    // already running may have been answered before the change, so wait for it and fetch again.
    async function refetchDataFresh() {
        if (dataInFlight) {
            try { await dataInFlight; } catch (err) { /* logged by loadData */ }
        }
        return refetchData();
    }

    // Fills the accordion's "Save selection as block" category <datalist>s; lives here because every
    // successful loadData() calls it.
    function refreshCategoryLists() {
        // <datalist> of the existing categories for both tabs; called whenever loadData() succeeds.
        try {
            if (!pb.data || !pb.data.blocks) return;
            const cats = new Set();
            for (const b of Object.values(pb.data.blocks)) {
                if (b && typeof b.category === "string" && b.category) cats.add(b.category);
            }
            const sorted = [...cats].sort();
            for (const tab of ["txt2img", "img2img"]) {
                const list = gradioApp().querySelector(`#pb_cats_${tab}`);
                if (!list) continue;
                list.replaceChildren(...sorted.map(c => {
                    const opt = document.createElement("option");
                    opt.value = c;
                    return opt;
                }));
            }
        } catch (err) {
            console.error("[PromptBlocks] could not fill the category list:", err);
        }
    }

    // The one category membership rule (same as pb_core.weights.in_category): does %category include
    // this block? Showing a block's own category reads b.category directly.
    function inCategory(block, category) {
        return !!block && typeof block === "object" && block.category === category;
    }

    PB.core = { pb, loadData, refetchData, refetchDataFresh, inCategory };
})();
