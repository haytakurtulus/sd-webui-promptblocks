// PromptBlocks bootstrap: registers the Save shortcut and the onUiLoaded setup, in the order the single
// promptblocks.js used (design notes section 29). Loaded last (Forge's filename order); does nothing
// but log one console error if a piece is missing.
(() => {
    const PB = window.PromptBlocks;
    const missing = ["core", "popup", "accordion", "tab"].filter(k => !PB || !PB[k]).map(k => "PromptBlocks." + k);
    if (typeof onUiLoaded !== "function") missing.push("onUiLoaded (WebUI script.js)");
    if (typeof gradioApp !== "function") missing.push("gradioApp (WebUI script.js)");
    if (missing.length) {
        console.error("[PromptBlocks] promptblocks_90_boot.js not initialised: missing " + missing.join(", ") +
            " (the promptblocks_*.js files must load in filename order)");
        return;
    }
    const { pb, loadData, refetchData } = PB.core;
    const { update, hide, onKeyDown, onPopupMouseMove, setPlainTokensOnly } = PB.popup;
    const { updatePreview, schedulePreview, updateRerollLabel, clearMessages, pinLastPicks, setupCreate,
            watchGeneration } = PB.accordion;
    const { onSaveShortcut, setupManagementTab } = PB.tab;

    document.addEventListener("keydown", onSaveShortcut, true);

    onUiLoaded(async () => {
        try {
            setupManagementTab();
        } catch (err) {
            console.error("[PromptBlocks] management tab setup failed:", err);
        }

        if (!(await loadData())) return;

        pb.popup = document.createElement("div");
        pb.popup.className = "pb-popup";
        pb.popup.style.display = "none";
        pb.popup.addEventListener("mousemove", onPopupMouseMove);
        document.body.appendChild(pb.popup);

        // The popup's own listeners on one field (prompt boxes and the Bans box, section 39).
        function attachPopup(el) {
            el.addEventListener("focus", refetchData);
            el.addEventListener("input", () => update(el));
            el.addEventListener("keydown", onKeyDown, true);
            el.addEventListener("blur", hide);
        }

        for (const id of ["txt2img_prompt", "img2img_prompt"]) {
            const ta = gradioApp().querySelector(`#${id} textarea`);
            if (!ta) {
                console.warn("[PromptBlocks] textarea not found:", id);
                continue;
            }
            const tab = id.replace("_prompt", "");
            attachPopup(ta);
            ta.addEventListener("input", () => schedulePreview(tab));
            // Section 24 fix 3: a prompt edit makes both accordion messages obsolete.
            ta.addEventListener("input", () => clearMessages(tab));

            const reroll = gradioApp().querySelector(`#pb_reroll_${tab}`);
            if (reroll) reroll.addEventListener("click", () => updatePreview(tab, true));
            const pinBtn = gradioApp().querySelector(`#pb_pin_${tab}`);
            if (pinBtn) pinBtn.addEventListener("click", () => pinLastPicks(tab));
            setupCreate(tab);
            watchGeneration(tab);
            const seedInput = gradioApp().querySelector(`#pb_block_seed_${tab} input`);
            if (seedInput) {
                // Section 33 E: the button label follows the field at once (the preview waits 400 ms).
                for (const ev of ["input", "change"]) {
                    seedInput.addEventListener(ev, () => updateRerollLabel(tab));
                }
                seedInput.addEventListener("input", () => schedulePreview(tab));
            } else console.warn("[PromptBlocks] Block seed field not found:", tab);
            updatePreview(tab, false);
        }
        // Section 39: the management tab's Bans box (a single-line Gradio Textbox -> <input>). Bans take
        // only ~name / %Category, so no sub-block / slot lists there; no preview or message hooks. It sits
        // in the collapsed "Random pick settings" accordion, which only hides it (display: none), so the
        // element exists at boot and opening the accordion later needs no re-attach.
        const bans = gradioApp().querySelector("#pb_bans input, #pb_bans textarea");
        if (bans) {
            setPlainTokensOnly(bans);
            attachPopup(bans);
        } else console.warn("[PromptBlocks] Bans box not found: #pb_bans (management tab not built?)");
        console.log("[PromptBlocks] autocomplete ready");
    });
})();
