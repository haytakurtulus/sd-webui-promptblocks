// PromptBlocks autocomplete popup: candidates, rendering, footer, caret position, keyboard (design notes
// section 29: needs promptblocks_00_core.js, loaded before this file by Forge's filename order).
(() => {
    const PB = window.PromptBlocks;
    if (!PB || !PB.core) {
        console.error("[PromptBlocks] promptblocks_10_popup.js not initialised: missing PromptBlocks.core (promptblocks_00_core.js must load first)");
        return;
    }
    const { pb, refetchData, inCategory } = PB.core;

    // Fields where only plain ~name / %Category tokens make sense (section 39: the management tab's Bans
    // box): no sub-block list after ~name. and no slot list after ~name*.
    const plainOnly = new WeakSet();

    function setPlainTokensOnly(el) {
        plainOnly.add(el);
    }

    function isOpen() {
        return pb.popup && pb.popup.style.display === "block";
    }

    // Popup opened from the closed state: refresh the data in the background; when it differs from what
    // the open list was built from, rebuild the list for the current token (design notes 23b).
    function refreshOpenPopup() {
        refetchData().then(ok => {
            // Closed meanwhile (Escape, blur, accepted item, no candidates): never reopen it.
            if (!ok || !isOpen() || !pb.ta || pb.builtKey === pb.dataKey) return;
            const keep = pb.items[pb.index] ? pb.items[pb.index].name : null;
            update(pb.ta, { rebuild: true, keep });
        });
    }

    function rankMatches(names, q) {
        const starts = [];
        const contains = [];
        for (const n of names) {
            const low = n.toLowerCase();
            if (low.startsWith(q)) starts.push(n);
            else if (low.includes(q)) contains.push(n);
        }
        return starts.concat(contains);
    }

    const MODE_LABELS = { include: "Include", exclude: "Exclude", random: "Random" };
    const SLOT_SEP = " · ";

    function buildSubCandidates(parent, typed) {
        const block = pb.data.blocks[parent];
        if (!block || !Array.isArray(block.subs)) return [];
        const byName = {};
        for (const s of block.subs) byName[s.name] = s;
        return rankMatches(block.subs.map(s => s.name), (typed || "").toLowerCase())
            .map(n => {
                const s = byName[n];
                let mode = MODE_LABELS[s.mode] || s.mode || "";
                // Section 14: the API sends "chance" only when it is not the default 50.
                if (s.mode === "random" && typeof s.chance === "number" && s.chance !== 50) {
                    mode += " " + s.chance + "%";
                }
                return { name: n, hint: s.slot ? mode + SLOT_SEP + s.slot : mode };
            });
    }

    function buildSlotCandidates(parent, typed) {
        // Distinct slots of the block's sub-blocks (any mode); hint = number of sub-blocks in that slot.
        const block = pb.data.blocks[parent];
        if (!block || !Array.isArray(block.subs)) return [];
        const counts = {};
        for (const s of block.subs) {
            if (s.slot) counts[s.slot] = (counts[s.slot] || 0) + 1;
        }
        return rankMatches(Object.keys(counts).sort(), (typed || "").toLowerCase())
            .map(slot => ({
                name: slot,
                hint: counts[slot] + (counts[slot] === 1 ? " sub-block" : " sub-blocks"),
            }));
    }

    function buildCandidates(symbol, typed) {
        const q = (typed || "").toLowerCase();
        const blocks = pb.data.blocks;
        if (symbol === pb.data.block_symbol) {
            return rankMatches(Object.keys(blocks).sort(), q)
                .map(n => ({
                    name: n,
                    hint: blocks[n].slot ? blocks[n].category + SLOT_SEP + blocks[n].slot : blocks[n].category,
                    thumb: blocks[n].thumb_v, isBlock: true,
                    inactive: blocks[n].active === false,
                }));
        }
        const counts = {};
        const active = {};
        for (const b of Object.values(blocks)) {
            counts[b.category] = (counts[b.category] || 0) + 1;
            active[b.category] = (active[b.category] || 0) + (b.active === false ? 0 : 1);
        }
        return rankMatches(Object.keys(counts).sort(), q)
            .map(c => ({
                name: c,
                hint: counts[c] + (counts[c] === 1 ? " block" : " blocks") + (active[c] < counts[c] ? ` (${active[c]} active)` : ""),
                inactive: active[c] === 0,
            }));
    }

    function hide() {
        if (pb.popup) pb.popup.style.display = "none";
        pb.items = [];
        pb.match = null;
    }

    // ---------- Popup footer: content of the highlighted item (design notes section 17) ----------

    const FOOTER_MAX = 200;

    function truncate(s, max) {
        s = String(s || "").replace(/\s+/g, " ").trim();
        return s.length > max ? s.slice(0, Math.max(0, max - 1)).trimEnd() + "…" : s;
    }

    function footerText(item) {
        const m = pb.match;
        if (!item || !m || !pb.data) return "";
        const blocks = pb.data.blocks || {};
        if (m.kind === "block") {
            const b = blocks[item.name];
            if (!b) return "";
            const meta = [];
            if (typeof b.lora === "string" && b.lora.trim()) meta.push(truncate(b.lora, 100));
            const n = Array.isArray(b.subs) ? b.subs.length : 0;
            if (n) meta.push(n + (n === 1 ? " sub-block" : " sub-blocks"));
            const tail = meta.join(SLOT_SEP);
            // Shorten the text first so the LoRA and the sub-block count stay visible.
            const room = Math.max(40, FOOTER_MAX - (tail ? tail.length + SLOT_SEP.length : 0));
            const text = truncate(b.text, room) || "(empty text)";
            return tail ? text + SLOT_SEP + tail : text;
        }
        if (m.kind === "sub" || m.kind === "slot") {
            const b = blocks[m.parent];
            const subs = b && Array.isArray(b.subs) ? b.subs : [];
            if (m.kind === "sub") {
                const s = subs.find(x => x.name === item.name);
                return s ? (truncate(s.text, FOOTER_MAX) || "(empty text)") : "";
            }
            return truncate(subs.filter(x => x.slot === item.name).map(x => x.name).join(", "), FOOTER_MAX);
        }
        if (m.kind === "category") {
            const names = Object.keys(blocks)
                .filter(n => inCategory(blocks[n], item.name) && blocks[n].active !== false)
                .sort();
            return names.length ? truncate(names.join(", "), FOOTER_MAX) : "no active blocks";
        }
        return "";
    }

    function updateFooter() {
        let footer = pb.popup.querySelector(".pb-footer");
        if (!footer) {
            footer = document.createElement("div");
            footer.className = "pb-footer";
            pb.popup.appendChild(footer);
        }
        const text = footerText(pb.items[pb.index]);
        footer.textContent = text;
        footer.style.display = text ? "" : "none";
    }

    // Hover moves the highlight in place (no list rebuild, so no mouseenter -> render loops).
    function setHighlight(i) {
        if (i === pb.index || i < 0 || i >= pb.items.length) return;
        pb.index = i;
        for (const row of pb.popup.querySelectorAll(".pb-item")) {
            row.classList.toggle("pb-active", Number(row.dataset.index) === i);
        }
        updateFooter();
        positionPopup(); // the footer height may have changed
    }

    let lastMouse = null;

    function onPopupMouseMove(e) {
        // Only real pointer movement: ignore events fired because the DOM / position changed under a
        // stationary cursor (e.g. after arrow keys re-rendered the list).
        if (lastMouse && lastMouse.x === e.clientX && lastMouse.y === e.clientY) return;
        lastMouse = { x: e.clientX, y: e.clientY };
        const row = e.target instanceof Element ? e.target.closest(".pb-item") : null;
        if (!row || !pb.popup.contains(row)) return;
        setHighlight(Number(row.dataset.index));
    }

    function render() {
        pb.popup.innerHTML = "";
        pb.items.forEach((item, i) => {
            const row = document.createElement("div");
            row.className = "pb-item" + (i === pb.index ? " pb-active" : "") + (item.inactive ? " pb-inactive" : "");
            row.dataset.index = String(i);
            if (item.inactive) {
                row.title = item.isBlock
                    ? "Inactive: not in random category picks"
                    : "All blocks inactive: this category picks nothing";
            }
            if (item.isBlock) {
                if (item.thumb) {
                    const img = document.createElement("img");
                    img.className = "pb-thumb";
                    img.src = `/promptblocks/thumb/${encodeURIComponent(item.name)}?v=${item.thumb}`;
                    row.append(img);
                } else {
                    const empty = document.createElement("div");
                    empty.className = "pb-thumb-empty";
                    row.append(empty);
                }
            }
            const name = document.createElement("span");
            name.className = "pb-name";
            name.textContent = pb.match.prefix + item.name;
            const hint = document.createElement("span");
            hint.className = "pb-hint";
            hint.textContent = item.hint;
            row.append(name, hint);
            row.addEventListener("mousedown", e => {
                e.preventDefault();
                pb.index = i;
                accept();
            });
            pb.popup.appendChild(row);
        });
        updateFooter(); // in the DOM before positionPopup() measures the popup
        pb.popup.style.display = "block";
        positionPopup();
    }

    // ---------- Popup position (at the caret, "mirror div") ----------

    const MIRROR_PROPS = [
        "fontFamily", "fontSize", "fontWeight", "fontStyle", "fontVariant", "fontStretch",
        "lineHeight", "letterSpacing", "wordSpacing", "textTransform", "textIndent", "tabSize",
        "textAlign", "direction",
        "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    ];
    let mirror = null;

    function getMirror() {
        if (!mirror) {
            mirror = document.createElement("div");
            mirror.setAttribute("aria-hidden", "true");
            const s = mirror.style;
            s.position = "absolute";
            s.top = "0";
            s.left = "-9999px";
            s.visibility = "hidden";
            s.pointerEvents = "none";
            s.overflow = "hidden";
            s.height = "auto";
            s.border = "0";
            s.margin = "0";
            s.boxSizing = "content-box";
            s.whiteSpace = "pre-wrap";
            s.wordWrap = "break-word";
            s.overflowWrap = "break-word";
            document.body.appendChild(mirror);
        }
        return mirror;
    }

    // Position of the token start, relative to the field's padding box (unscrolled),
    // plus the top/bottom of its line. Returns null when it cannot be measured.
    // The field is a <textarea> (prompt boxes) or a single-line <input> (section 39: a Gradio 4 Textbox
    // with lines=1, max_lines=1 renders an <input type="text">, e.g. the Bans box). An input never wraps
    // and scrolls horizontally; its "line" is the whole box.
    function measureTokenStart(ta, start, end) {
        if (!ta.clientWidth || !ta.clientHeight) return null;
        const single = ta.tagName === "INPUT";
        const cs = window.getComputedStyle(ta);
        const m = getMirror();
        for (const p of MIRROR_PROPS) m.style[p] = cs[p];
        const padL = parseFloat(cs.paddingLeft) || 0;
        const padR = parseFloat(cs.paddingRight) || 0;
        if (single) {
            m.style.whiteSpace = "pre";
            m.style.width = "auto";
        } else {
            m.style.whiteSpace = "pre-wrap";
            // clientWidth excludes border and a vertical scrollbar, so wrapping matches the textarea.
            m.style.width = Math.max(0, ta.clientWidth - padL - padR) + "px";
        }

        const value = ta.value;
        m.textContent = value.slice(0, start);
        const marker = document.createElement("span");
        // The token itself (or a zero-width space) so the marker wraps exactly like the token.
        marker.textContent = value.slice(start, end) || "\u200b";
        m.appendChild(marker);
        // Text after the token keeps the line-breaking of the current word identical.
        m.appendChild(document.createTextNode(value.slice(end) || ""));

        const spanH = marker.offsetHeight;
        let lh = parseFloat(cs.lineHeight);
        if (!Number.isFinite(lh)) lh = spanH;
        const halfLeading = (lh - spanH) / 2;
        const x = marker.offsetLeft;
        let lineTop = marker.offsetTop - halfLeading;
        let lineBottom = marker.offsetTop + spanH + halfLeading;
        if (single) {
            // Below / above the whole input box (positionPopup adds clientTop back).
            lineTop = -ta.clientTop;
            lineBottom = ta.getBoundingClientRect().height - ta.clientTop;
        }
        m.textContent = "";  // do not keep a copy of the prompt in the DOM
        if (![x, lineTop, lineBottom].every(Number.isFinite)) return null;
        return { x, lineTop, lineBottom };
    }

    function positionPopup() {
        const popup = pb.popup;
        const ta = pb.ta;
        const r = ta.getBoundingClientRect();
        // Fallback: under the textarea (old behaviour).
        let left = r.left;
        let top = r.bottom + 4;
        try {
            const pos = pb.match ? measureTokenStart(ta, pb.match.start, pb.match.end) : null;
            if (pos) {
                // Viewport coordinates of the token start and its line.
                const baseX = r.left + ta.clientLeft - ta.scrollLeft;
                const baseY = r.top + ta.clientTop - ta.scrollTop;
                const lineTop = baseY + pos.lineTop;
                left = baseX + pos.x;
                top = baseY + pos.lineBottom + 2;

                const vw = document.documentElement.clientWidth || window.innerWidth;
                const vh = document.documentElement.clientHeight || window.innerHeight;
                const w = popup.offsetWidth;
                const h = popup.offsetHeight;
                if (left + w > vw) left = vw - w - 4;
                if (top + h > vh) top = lineTop - h - 2;
                left = Math.max(0, left);
                top = Math.max(0, top);
            }
        } catch (err) {
            left = r.left;
            top = r.bottom + 4;
        }
        popup.style.left = (left + window.scrollX) + "px";
        popup.style.top = (top + window.scrollY) + "px";
    }

    // opts.rebuild: called by refreshOpenPopup() after new data arrived for the open popup; keeps the
    // highlighted item (opts.keep, by name) and never starts another refetch.
    function update(ta, opts) {
        const rebuild = !!(opts && opts.rebuild);
        if (!rebuild && pb.suppress) {
            pb.suppress = false;
            hide();
            return;
        }
        if (!pb.data) return hide();
        const wasOpen = isOpen();
        const pos = ta.selectionStart;
        const before = ta.value.slice(0, pos);
        let items, prefix, start, kind, parent = null;
        const plain = plainOnly.has(ta);
        const dm = !plain && pb.slotRe ? before.match(pb.slotRe) : null;
        const sm = !plain && !dm && pb.subRe ? before.match(pb.subRe) : null;
        if (dm) {
            // Slots of an existing block's sub-blocks; unknown block or no slotted subs shows nothing.
            items = buildSlotCandidates(dm[2], dm[3]);
            prefix = dm[1] + dm[2] + (pb.data.slot_draw_separator || "*");
            start = pos - dm[0].length;
            kind = "slot";
            parent = dm[2];
        } else if (sm) {
            // Sub-blocks of an existing block only; an unknown block before the dot shows nothing.
            items = buildSubCandidates(sm[2], sm[3]);
            prefix = sm[1] + sm[2] + (pb.data.sub_separator || ".");
            start = pos - sm[0].length;
            kind = "sub";
            parent = sm[2];
        } else {
            const m = before.match(pb.tokenRe);
            if (!m) return hide();
            items = buildCandidates(m[1], m[2]);
            prefix = m[1];
            start = pos - m[0].length;
            kind = m[1] === pb.data.block_symbol ? "block" : "category";
        }
        items = items.slice(0, 10);
        if (!items.length) return hide();
        pb.ta = ta;
        pb.items = items;
        const kept = rebuild && opts.keep != null ? items.findIndex(it => it.name === opts.keep) : -1;
        pb.index = kept >= 0 ? kept : 0;
        // kind / parent are used only by the footer (section 17).
        pb.match = { prefix, start, end: pos, kind, parent };
        pb.builtKey = pb.dataKey;
        render();
        if (!wasOpen && !rebuild) refreshOpenPopup();
    }

    function accept() {
        const ta = pb.ta;
        const { prefix, start, end } = pb.match;
        const insert = prefix + pb.items[pb.index].name;
        ta.value = ta.value.slice(0, start) + insert + ta.value.slice(end);
        const caret = start + insert.length;
        ta.setSelectionRange(caret, caret);
        hide();
        pb.suppress = true;
        ta.dispatchEvent(new Event("input", { bubbles: true }));
    }

    function onKeyDown(e) {
        if (!isOpen() || e.target !== pb.ta) return;
        if (e.ctrlKey || e.altKey || e.metaKey) return;
        if (e.key === "ArrowDown") {
            pb.index = (pb.index + 1) % pb.items.length;
            render();
        } else if (e.key === "ArrowUp") {
            pb.index = (pb.index - 1 + pb.items.length) % pb.items.length;
            render();
        } else if (e.key === "Enter" || e.key === "Tab") {
            accept();
        } else if (e.key === "Escape") {
            hide();
        } else {
            return;
        }
        e.preventDefault();
        e.stopPropagation();
    }

    PB.popup = { update, hide, onKeyDown, onPopupMouseMove, setPlainTokensOnly };
})();
