// PromptBlocks accordion extras (txt2img / img2img): preview panel, message lines, "Pin last picks",
// "Save selection as block" (design notes section 29: needs promptblocks_00_core.js, loaded before this
// file by Forge's filename order).
(() => {
    const PB = window.PromptBlocks;
    if (!PB || !PB.core) {
        console.error("[PromptBlocks] promptblocks_20_accordion.js not initialised: missing PromptBlocks.core (promptblocks_00_core.js must load first)");
        return;
    }
    const { pb, refetchDataFresh } = PB.core;

    // ---------- Preview panel ----------

    const previewTimers = {};

    function readSeed(tab) {
        const input = gradioApp().querySelector(`#pb_block_seed_${tab} input`);
        if (!input) return null;
        const v = parseInt(input.value, 10);
        return Number.isNaN(v) || v < 0 ? null : v;
    }

    // Section 33 E: with a fixed Block seed the button does not show what Generate will make, so its
    // label says so; with -1 it is the plain "Another example". Called on every seed field input /
    // change and on every preview render.
    const REROLL_LABEL = "Another example";
    const REROLL_LABEL_FIXED = "Random example (not this seed)";

    function updateRerollLabel(tab) {
        const btn = gradioApp().querySelector(`#pb_reroll_${tab}`);
        if (!btn) return;
        const label = readSeed(tab) === null ? REROLL_LABEL : REROLL_LABEL_FIXED;
        if (btn.textContent !== label) btn.textContent = label;
    }

    async function updatePreview(tab, forceRandom) {
        const box = gradioApp().querySelector(`#pb_preview_${tab}`);
        const ta = gradioApp().querySelector(`#${tab}_prompt textarea`);
        updateRerollLabel(tab);
        if (!box || !ta) return;

        let res;
        try {
            const r = await fetch("/promptblocks/preview", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: ta.value, seed: forceRandom ? null : readSeed(tab) }),
            });
            res = await r.json();
        } catch (err) {
            box.textContent = "Preview failed: " + err;
            return;
        }

        box.innerHTML = "";
        if (res.error) {
            const e = document.createElement("div");
            e.className = "pb-warn";
            e.textContent = "⚠ " + res.error;
            box.append(e);
            return;
        }
        const label = document.createElement("div");
        label.className = "pb-preview-label";
        label.textContent = res.from_field
            ? `Exact first image (seed ${res.seed}, from Block seed field):`
            : `Random example (seed ${res.seed}):`;
        const text = document.createElement("div");
        text.className = "pb-preview-text";
        text.textContent = res.text || "(empty prompt)";
        box.append(label, text);
        // Section 33 E: while the Block seed field is >= 0, say which seed Generate will use.
        const fieldSeed = readSeed(tab);
        if (fieldSeed !== null) {
            const seedLine = document.createElement("div");
            seedLine.className = "pb-preview-subs pb-preview-seed";
            seedLine.textContent = `Generate will use seed ${fieldSeed}`;
            box.append(seedLine);
        }
        const picked = [];
        const sep = pb.data ? pb.data.sub_separator || "." : ".";
        for (const p of res.subs_picked || []) {
            const s = p.parent + sep + p.sub;
            if (!picked.includes(s)) picked.push(s);
        }
        if (picked.length) {
            const subsLine = document.createElement("div");
            subsLine.className = "pb-preview-subs";
            subsLine.textContent = "Sub-blocks: " + picked.join(", ");
            box.append(subsLine);
        }
        const occupied = res.occupied_slots || [];
        if (occupied.length) {
            const slotsLine = document.createElement("div");
            slotsLine.className = "pb-preview-subs";
            slotsLine.textContent = "Occupied slots: " + occupied.join(", ");
            box.append(slotsLine);
        }
        // Section 31a: what the used blocks add to each ADetailer tab (only tabs with additions).
        const ad = res.adetailer || {};
        for (const t of ad.tabs || []) {
            const adLine = document.createElement("div");
            adLine.className = "pb-preview-subs pb-preview-ad";
            adLine.textContent = `ADetailer ${t.label}: + ` + (t.items || []).map((i) => i.text).join(", ");
            adLine.title = (t.items || []).map((i) => `${i.block}: ${i.text}`).join("\n");
            box.append(adLine);
        }
        for (const e of ad.errors || []) {
            const w = document.createElement("div");
            w.className = "pb-warn";
            w.textContent = "⚠ " + e;
            box.append(w);
        }
        // Section 38: what a ban changed in this example (only lines when something changed).
        for (const line of res.bans || []) {
            const w = document.createElement("div");
            w.className = "pb-warn pb-preview-ban";
            w.textContent = line;
            box.append(w);
        }
        if (res.unknown.length) {
            const w = document.createElement("div");
            w.className = "pb-warn";
            w.textContent = "⚠ Unknown: " + res.unknown.join(", ");
            box.append(w);
        }
        for (const c of res.all_inactive || []) {
            const w = document.createElement("div");
            w.className = "pb-warn";
            w.textContent = `⚠ ${pb.data ? pb.data.category_symbol : "%"}${c}: all blocks inactive`;
            box.append(w);
        }
    }

    function schedulePreview(tab) {
        clearTimeout(previewTimers[tab]);
        previewTimers[tab] = setTimeout(() => updatePreview(tab, false), 400);
    }

    // ---------- Accordion message lines (design notes section 24 fix 3) ----------
    // #pb_pin_msg_<tab> and #pb_create_msg_<tab> show transient messages: each one is cleared by a
    // timeout (restarted when the message is replaced), by any input event of the tab's prompt textarea
    // (our own Pin / Save selection replace the prompt and dispatch "input" BEFORE they show their
    // message, so a success clears the other line and keeps its own), and the Pin line also by a new
    // Pin press and by the start / end of a generation (watchGeneration).

    const MSG_MS = 6000;
    const MSG_WARN_MS = 10000;
    const msgTimers = {};

    function showMessage(id, text, warn) {
        // Never throws: a missing element only means there is nothing to show.
        try {
            clearTimeout(msgTimers[id]);
            delete msgTimers[id];
            const box = gradioApp().querySelector(`#${id}`);
            if (!box) return;
            box.textContent = text || "";
            box.classList.toggle("pb-create-msg-warn", !!(text && warn));
            if (!text) return;
            msgTimers[id] = setTimeout(() => {
                delete msgTimers[id];
                const el = gradioApp().querySelector(`#${id}`);
                if (!el) return;
                el.textContent = "";
                el.classList.remove("pb-create-msg-warn");
            }, warn ? MSG_WARN_MS : MSG_MS);
        } catch (err) {
            console.error("[PromptBlocks] message line failed:", err);
        }
    }

    function clearMessages(tab) {
        showMessage(`pb_create_msg_${tab}`, "");
        showMessage(`pb_pin_msg_${tab}`, "");
    }

    // The Pin line talks about the picks of the last Generate; they change when a new one runs. Forge
    // shows #<tab>_interrupt while a generation runs and hides it again at the end (ui.js
    // showSubmitButtons / setSubmitButtonsVisibility set its style.display), so any change of that
    // display value clears the Pin line. Without the button only the other rules apply.
    function watchGeneration(tab) {
        try {
            const btn = gradioApp().querySelector(`#${tab}_interrupt`);
            if (!btn) return;
            let shown = btn.style.display;
            new MutationObserver(() => {
                if (btn.style.display === shown) return;
                shown = btn.style.display;
                showMessage(`pb_pin_msg_${tab}`, "");
            }).observe(btn, { attributes: true, attributeFilter: ["style"] });
        } catch (err) {
            console.error("[PromptBlocks] generation watch failed:", err);
        }
    }

    // ---------- "Pin last picks" (design notes section 15) ----------

    // Pin messages have their own line (#pb_pin_msg_<tab>, design notes 23b): the preview box is
    // rewritten by every preview refresh, which used to wipe the message right after the first press.
    function showPinMessage(tab, text, warn) {
        showMessage(`pb_pin_msg_${tab}`, text, warn);
    }

    function pinMessage(res) {
        // -> [text, warn]
        if (res.replaced > 0) {
            return [`Pinned ${res.replaced} pick${res.replaced === 1 ? "" : "s"} from the last Generate.`, false];
        }
        if (!res.available) {
            return res.generated
                ? ["The last Generate made no random picks - nothing to pin", true]
                : ["No picks recorded yet - generate first", true];
        }
        return ["Nothing to pin in this prompt", true];
    }

    async function pinLastPicks(tab) {
        const ta = gradioApp().querySelector(`#${tab}_prompt textarea`);
        if (!ta) return;
        showPinMessage(tab, "", false); // a repeated identical message still visibly re-appears
        let res;
        try {
            const r = await fetch("/promptblocks/pin", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: ta.value, tab }),
            });
            res = await r.json();
        } catch (err) {
            showPinMessage(tab, "⚠ Pin failed: " + err, true);
            return;
        }
        if (!res || typeof res !== "object") {
            showPinMessage(tab, "⚠ Pin failed", true);
            return;
        }
        if (res.replaced > 0 && typeof res.prompt === "string") {
            ta.value = res.prompt;
            pb.suppress = true; // no autocomplete popup for this programmatic change
            ta.dispatchEvent(new Event("input", { bubbles: true })); // also schedules the preview refresh
        }
        const [text, warn] = pinMessage(res);
        showPinMessage(tab, text, warn);
    }

    // ---------- Save prompt selection as a block (design notes section 16) ----------

    // The prompt textarea's CURRENT selection, read at click time (design notes 23b). A blurred textarea
    // keeps its selectionStart / selectionEnd, so focusing the Name / Category inputs does not lose it,
    // and a later click elsewhere in the prompt (caret only) correctly means "no selection".
    // Returns { start, end, text } without edge whitespace, or null (collapsed / whitespace only).
    function currentSelection(ta) {
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        if (typeof start !== "number" || typeof end !== "number" || start >= end) return null;
        // Leave edge whitespace in the prompt: "a, blue eyes ,b" with " blue eyes " -> "a, ~x ,b".
        const raw = ta.value.slice(start, end);
        const lead = raw.length - raw.trimStart().length;
        const text = raw.trim();
        if (!text) return null;
        return { start: start + lead, end: start + lead + text.length, text };
    }

    function showCreateMessage(tab, text, warn) {
        showMessage(`pb_create_msg_${tab}`, text, warn);
    }

    async function createFromSelection(tab) {
        const app = gradioApp();
        const ta = app.querySelector(`#${tab}_prompt textarea`);
        const nameInput = app.querySelector(`#pb_new_name_${tab}`);
        const catInput = app.querySelector(`#pb_new_cat_${tab}`);
        const btn = app.querySelector(`#pb_create_${tab}`);
        if (!ta || !nameInput || !catInput) return;
        if (btn && btn.disabled) return;  // a request is already running
        const sel = currentSelection(ta);
        if (!sel) {
            showCreateMessage(tab, "Select some text in the prompt first", true);
            return;
        }

        let res;
        if (btn) btn.disabled = true;
        try {
            const r = await fetch("/promptblocks/create", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: nameInput.value, category: catInput.value, text: sel.text }),
            });
            res = await r.json();
        } catch (err) {
            showCreateMessage(tab, "⚠ Save failed: " + err, true);
            return;
        } finally {
            if (btn) btn.disabled = false;
        }
        if (!res || !res.ok) {
            showCreateMessage(tab, "⚠ " + ((res && res.error) || "Save failed"), true);
            return;
        }

        const token = res.token;
        // The prompt may have been edited while the request was running: only replace the exact range.
        if (ta.value.slice(sel.start, sel.end) === sel.text) {
            ta.value = ta.value.slice(0, sel.start) + token + ta.value.slice(sel.end);
            const caret = sel.start + token.length;
            ta.setSelectionRange(caret, caret);
            pb.suppress = true; // no autocomplete popup for this programmatic change
            ta.dispatchEvent(new Event("input", { bubbles: true }));
            showCreateMessage(tab, "Saved " + token, false);
        } else {
            showCreateMessage(tab, `Saved ${token} (the prompt changed meanwhile; insert ${token} yourself)`, true);
        }
        nameInput.value = "";
        // Popup + category list know the new block. "Fresh": a fetch already running may predate the save.
        await refetchDataFresh();
    }

    function setupCreate(tab) {
        const btn = gradioApp().querySelector(`#pb_create_${tab}`);
        if (!btn) {
            console.warn("[PromptBlocks] create row not found:", tab);
            return;
        }
        btn.addEventListener("click", () => createFromSelection(tab));
        for (const id of [`pb_new_name_${tab}`, `pb_new_cat_${tab}`]) {
            const input = gradioApp().querySelector(`#${id}`);
            if (!input) continue;
            input.addEventListener("keydown", e => {
                // Plain Enter = the button. Modified keys (e.g. Ctrl+Enter = Forge's Generate) pass through.
                if (e.key !== "Enter" || e.ctrlKey || e.metaKey || e.altKey || e.shiftKey || e.isComposing) return;
                e.preventDefault();
                e.stopPropagation();
                createFromSelection(tab);
            });
        }
    }

    PB.accordion = { updatePreview, schedulePreview, updateRerollLabel, clearMessages, pinLastPicks, setupCreate,
                     watchGeneration };
})();
