// PromptBlocks management tab helpers: Ctrl+S / Ctrl+Enter, tooltips, toast, "modified" marker, loaded-tile
// highlight (design notes section 29), sub-block row classes by mode (section 37 C), dimmed inactive tiles and
// tile hover summaries (section 40; the summaries use PB.core's block data when it is there, nothing else
// needs the other files); promptblocks_90_boot.js
// registers the shortcut and calls setupManagementTab().
(() => {
    const PB = window.PromptBlocks = window.PromptBlocks || {};

    // ---------- Management tab: Ctrl+S / Ctrl+Enter presses Save ----------

    let saveShortcutBusy = false;

    function onSaveShortcut(e) {
        if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
        if (e.key !== "s" && e.key !== "S" && e.key !== "Enter") return;
        const tab = gradioApp().querySelector("#tab_promptblocks_tab");
        // Only while focus is inside the PromptBlocks tab; everything else is left alone.
        if (!tab || !(e.target instanceof Node) || !tab.contains(e.target)) return;
        const btn = tab.querySelector("#pb_save_btn");
        if (!btn) return;
        e.preventDefault();  // no browser "Save page" dialog
        if (e.repeat || saveShortcutBusy) return;
        saveShortcutBusy = true;
        // Blur first so Gradio commits the field being edited (e.g. a custom dropdown value),
        // then click after a short delay.
        const active = document.activeElement;
        if (active && typeof active.blur === "function") active.blur();
        setTimeout(() => {
            saveShortcutBusy = false;
            btn.click();
        }, 150);
    }

    // ---------- Management tab: tooltips + toast that repeats #pb_status ----------
    // Independent of loadData(): set up even when /promptblocks/blocks cannot be fetched.

    const TOAST_MS = 4000;
    const TOAST_WARN_MS = 8000;
    const toast = { el: null, timer: null, lastText: "", armed: false, check: null };

    function pbTab() {
        return gradioApp().querySelector("#tab_promptblocks_tab");
    }

    function tabVisible() {
        const tab = pbTab();
        return !!tab && tab.getClientRects().length > 0;
    }

    function hideToast() {
        if (!toast.el) return;
        clearTimeout(toast.timer);
        toast.el.classList.remove("pb-toast-show");
    }

    function showToast(text) {
        if (!toast.el || !text || !tabVisible()) return hideToast();
        const warn = /^(⚠|Not saved|Invalid)/.test(text);
        toast.el.textContent = text;
        toast.el.classList.toggle("pb-toast-warn", warn);
        toast.el.classList.add("pb-toast-show");
        clearTimeout(toast.timer);
        toast.timer = setTimeout(hideToast, warn ? TOAST_WARN_MS : TOAST_MS);
    }

    function statusText(status) {
        // Rendered Markdown only (span.md), not the loading indicator Gradio adds while pending.
        const md = status.querySelector(".md") || status.querySelector(".prose");
        return ((md || status).textContent || "").trim();
    }

    function statusPending(status) {
        // Gradio's status tracker (.wrap) loses its "hide" class while the event is running.
        return !!status.querySelector(".wrap:not(.hide)");
    }

    function setupToast() {
        const tab = pbTab();
        const status = gradioApp().querySelector("#pb_status");
        if (!tab || !status) {
            console.warn("[PromptBlocks] management tab / status not found; no toast");
            return;
        }
        toast.el = document.createElement("div");
        toast.el.className = "pb-toast";
        toast.el.setAttribute("role", "status");
        toast.el.title = "Click to dismiss";
        toast.el.addEventListener("click", hideToast);
        // Inside the tab: hidden together with it when another Forge tab is shown.
        tab.appendChild(toast.el);

        const check = () => {
            if (statusPending(status)) return;
            const text = statusText(status);
            if (!text) {
                toast.lastText = "";
                toast.armed = false;
                return hideToast();
            }
            // Same text again (e.g. saving the same block twice) is shown only after a Save click.
            if (text !== toast.lastText || toast.armed) {
                toast.lastText = text;
                toast.armed = false;
                showToast(text);
            }
        };
        let debounce = null;
        new MutationObserver(() => {
            clearTimeout(debounce);
            debounce = setTimeout(check, 80);
        }).observe(status, {
            childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class"],
        });
        for (const id of ["pb_save_btn", "pb_save_fab"]) {
            const btn = gradioApp().querySelector(`#${id}`);
            if (btn) btn.addEventListener("click", () => { toast.armed = true; });
        }
    }

    // ---------- Management tab: "modified" marker on the Save buttons (design notes sections 20, 26) ----------
    // Cosmetic only; the server decides "modified" itself when a block switch auto-saves. Set by user edits
    // inside the form column (#pb_left) and by "dirty N" signals; cleared by "clean N" signals. The signal
    // element #pb_form_epoch is rewritten by the server whenever a block is loaded, saved, reloaded or the
    // form blanked ("clean N"), or when a handler changed the form itself, e.g. Duplicate or a thumbnail
    // ("dirty N"). A refused switch sends no signal: the form keeps its changes, and the marker stays.

    function setSaveDirty(on) {
        for (const id of ["pb_save_btn", "pb_save_fab"]) {
            const btn = gradioApp().querySelector(`#${id}`);
            if (btn) btn.classList.toggle("pb-dirty", on);
        }
    }

    function setupDirtyMarker() {
        const left = gradioApp().querySelector("#pb_left");
        const signal = gradioApp().querySelector("#pb_form_epoch");
        if (!left || !signal) {
            console.warn("[PromptBlocks] form / form signal not found; no Save marker");
            return;
        }
        // Gradio sets field values from the server without DOM events, so every input / change event in
        // the form comes from the user (typed, pasted, or dispatched by a script / automation).
        left.addEventListener("input", () => setSaveDirty(true), true);
        left.addEventListener("change", () => setSaveDirty(true), true);
        left.addEventListener("mousedown", e => {
            // Choosing an option of a dropdown (Category, Mode, Slot) fires no DOM input event.
            if (e.target instanceof Element && e.target.closest("ul.options li")) setSaveDirty(true);
        }, true);
        left.addEventListener("click", e => {
            if (e.target instanceof Element && e.target.closest(".pb-move-btn")) setSaveDirty(true);
        }, true);

        // Read only the data attribute: the element's text also contains Gradio's loading indicator
        // while an event runs.
        const signalValue = () => {
            const span = signal.querySelector("[data-pb-form]");
            return span ? (span.getAttribute("data-pb-form") || "").trim() : "";
        };
        let last = signalValue();
        new MutationObserver(() => {
            const text = signalValue();
            if (!text || text === last) return;
            last = text;
            const kind = text.split(/\s+/)[0];
            if (kind === "clean") setSaveDirty(false);
            else if (kind === "dirty") setSaveDirty(true);
        }).observe(signal, {
            childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["data-pb-form"],
        });
    }

    // ---------- Management tab: sub-block rows dimmed by mode (design notes section 37 C) ----------
    // Cosmetic only. Each .pb-subrow gets pb-sub-exclude (mode Exclude: the row is dimmed) and pb-sub-nochance
    // (mode Include / Exclude: the % box is dimmed) from its Mode dropdown's shown value (the labels are the
    // capitalised modes). Gradio sets values from the server without DOM events, so besides the user's own
    // input / change / option clicks this runs on form signals and status changes (block load, Reload, the
    // All <mode> buttons, the bulk tool) and in the tile-highlight poll as a safety net. style.css uses only
    // opacity: focus, clicks and typing are never blocked.

    function syncSubRows() {
        for (const dd of gradioApp().querySelectorAll('#pb_subs [id^="pb_sub_mode_"]')) {
            const row = dd.closest(".pb-subrow");
            const input = dd.querySelector("input");
            if (!row || !input) continue;
            const mode = (input.value || "").trim().toLowerCase();
            const exclude = mode === "exclude";
            const nochance = mode !== "random";
            if (row.classList.contains("pb-sub-exclude") !== exclude) row.classList.toggle("pb-sub-exclude", exclude);
            if (row.classList.contains("pb-sub-nochance") !== nochance) row.classList.toggle("pb-sub-nochance", nochance);
        }
    }

    function setupSubRowClasses() {
        const panel = gradioApp().querySelector("#pb_subs");
        if (!panel) {
            console.warn("[PromptBlocks] sub-block panel not found; no row classes");
            return;
        }
        let timer = null;
        const schedule = () => {
            clearTimeout(timer);
            timer = setTimeout(syncSubRows, 60);
        };
        for (const type of ["input", "change", "focusout"]) panel.addEventListener(type, schedule, true);
        panel.addEventListener("mousedown", e => {
            if (e.target instanceof Element && e.target.closest("ul.options li")) schedule();
        }, true);
        for (const id of ["pb_form_epoch", "pb_status"]) {
            const el = gradioApp().querySelector(`#${id}`);
            if (el) new MutationObserver(schedule).observe(el, {
                childList: true, subtree: true, characterData: true, attributes: true,
            });
        }
        syncSubRows();
    }

    // ---------- Management tab: highlight the loaded block's tile (design notes section 21) ----------
    // Cosmetic only, done here instead of the gallery's selected_index: Gradio fires "select" only when
    // that index changes, so a server-side highlight would swallow the next click on the loaded tile. The
    // tile whose caption (block name, optionally followed by " (off)") equals the Block dropdown's value
    // gets the class pb-loaded. The dropdown is the source: a block switch sets it (and puts it back after
    // a refused switch), it is emptied by New / Delete / Duplicate, and follows Save / Rename. Re-evaluated
    // on gallery rebuilds, form signals, status changes and dropdown blur, with a slow poll as a safety net.

    // Section 40: inactive tiles are dimmed (class pb-tile-off) and every tile gets a hover summary
    // (title). Inactive = the caption ends with the server's " (off)" suffix (pb_core.browser.INACTIVE_SUFFIX,
    // checked by a pytest against this file), so the dimming never goes stale. The summary comes from
    // pb.data (/promptblocks/blocks), refetched (debounced) when the gallery content, the status line or
    // the form signal changes; without data a tile's title is just its caption.
    const INACTIVE_SUFFIX = " (off)";
    const TITLE_TEXT_CHARS = 160;

    function tileCaption(btn) {
        const img = btn.querySelector("img");
        let cap = img ? img.getAttribute("alt") || "" : "";
        if (!cap) {
            const label = btn.querySelector(".caption-label");
            cap = label ? label.textContent || "" : "";
        }
        return cap.trim();
    }

    function tileName(btn) {
        return tileCaption(btn).split(/\s+/)[0] || "";
    }

    function tileIsOff(btn) {
        return tileCaption(btn).endsWith(INACTIVE_SUFFIX);
    }

    // Multi-line hover summary of one block from pb.data (fields as /promptblocks/blocks sends them).
    function tileTitle(name, off) {
        const core = PB.core;
        const b = core && core.pb.data && core.pb.data.blocks ? core.pb.data.blocks[name] : null;
        if (!b || typeof b !== "object") return name + (off ? INACTIVE_SUFFIX : "");
        const head = [name + (off ? INACTIVE_SUFFIX : "")];
        if (typeof b.category === "string" && b.category) head.push("Category: " + b.category);
        if (typeof b.weight === "number" && b.weight !== 1) head.push("Weight: " + b.weight);
        if (typeof b.slot === "string" && b.slot) head.push("Slot: " + b.slot);
        const lines = [head.join(" · ")];
        const text = typeof b.text === "string" ? b.text.trim() : "";
        if (text) lines.push(text.length > TITLE_TEXT_CHARS ? text.slice(0, TITLE_TEXT_CHARS).trimEnd() + "…" : text);
        if (typeof b.lora === "string" && b.lora) lines.push("LoRA: " + b.lora);
        const subs = Array.isArray(b.subs) ? b.subs.map(s => s && s.name).filter(n => typeof n === "string" && n) : [];
        if (subs.length) lines.push("Sub-blocks: " + subs.join(", "));
        const bans = Array.isArray(b.bans) ? b.bans.filter(t => typeof t === "string" && t.trim()).map(t => t.trim()) : [];
        if (bans.length) lines.push("Bans: " + bans.join(", "));
        return lines.join("\n");
    }

    function setupLoadedHighlight() {
        const gallery = gradioApp().querySelector("#pb_gallery");
        const picker = gradioApp().querySelector("#pb_picker input");
        if (!gallery || !picker) {
            console.warn("[PromptBlocks] gallery / Block dropdown not found; no tile highlight");
            return;
        }
        let current = "";
        const apply = () => {
            // While the dropdown is focused its input holds the typed filter text: keep the old name.
            if (document.activeElement !== picker) current = (picker.value || "").trim();
            for (const btn of gallery.querySelectorAll("button.thumbnail-item")) {
                const name = tileName(btn);
                const on = !!current && name === current;
                if (btn.classList.contains("pb-loaded") !== on) btn.classList.toggle("pb-loaded", on);
                const off = tileIsOff(btn);
                if (btn.classList.contains("pb-tile-off") !== off) btn.classList.toggle("pb-tile-off", off);
                const title = tileTitle(name, off);
                if (btn.title !== title) btn.title = title;
            }
        };
        let timer = null;
        const schedule = () => {
            clearTimeout(timer);
            timer = setTimeout(apply, 60);
        };
        // Fresh block data for the hover summaries, at most one request per quiet 400 ms.
        let dataTimer = null;
        const scheduleData = () => {
            clearTimeout(dataTimer);
            dataTimer = setTimeout(() => {
                const core = PB.core;
                if (!core || typeof core.refetchData !== "function") return;
                core.refetchData().then(schedule, schedule);
            }, 400);
        };
        const onChange = () => {
            schedule();
            scheduleData();
        };
        // Class / title changes are not observed (attributeFilter), so apply() never re-triggers itself.
        new MutationObserver(onChange).observe(gallery, {
            childList: true, subtree: true, attributes: true, attributeFilter: ["src", "alt"],
        });
        for (const id of ["pb_form_epoch", "pb_status"]) {
            const el = gradioApp().querySelector(`#${id}`);
            if (el) new MutationObserver(onChange).observe(el, { childList: true, subtree: true, characterData: true });
        }
        picker.addEventListener("blur", schedule);
        setInterval(() => {
            if (gallery.offsetParent === null) return;
            apply();
            syncSubRows();  // section 37 C: safety net for programmatic Mode updates
        }, 500);
        apply();
        scheduleData();
    }

    function setupManagementTab() {
        const tips = {
            pb_save_btn: "Save (Ctrl+S or Ctrl+Enter inside this tab)",
            pb_save_fab: "Save (Ctrl+S or Ctrl+Enter inside this tab)",
            pb_reload_btn: "Reload: discard the changes in the form and show the saved version again (a new block: blank form)",
            pb_refresh_btn: "Refresh: reload the block list (e.g. after editing blocks.json by hand)",
            pb_duplicate_btn: "Copy this form under a new name; Save creates the copy",
            pb_subs_all_include: "Set every filled sub-block row of this form to Include (press Save to keep it)",
            pb_subs_all_exclude: "Set every filled sub-block row of this form to Exclude (press Save to keep it)",
            pb_subs_all_random: "Set every filled sub-block row of this form to Random (press Save to keep it)",
        };
        for (const [id, tip] of Object.entries(tips)) {
            const el = gradioApp().querySelector(`#${id}`);
            if (el) el.title = tip;
        }
        const pickerInput = gradioApp().querySelector("#pb_picker input");
        if (pickerInput) pickerInput.placeholder = "Select a block to edit, or press New";
        setupToast();
        setupDirtyMarker();
        setupSubRowClasses();
        setupLoadedHighlight();
    }

    PB.tab = { onSaveShortcut, setupManagementTab };
})();
