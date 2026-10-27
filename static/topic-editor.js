(function () {
    const root = document.querySelector("[data-topic-editor]");
    if (!root) return;

    const textarea = root.querySelector("[data-topic-output]");
    const list = root.querySelector("[data-topic-list]");
    const countLabel = root.querySelector("[data-topic-count]");
    const diffList = root.querySelector("[data-topic-diff]");
    const submitButton = root.querySelector("[data-topic-submit]");
    if (!textarea || !list) return;

    const original = (root.dataset.original || "")
        .split("||")
        .map((item) => item.trim())
        .filter(Boolean);
    const genericTopics = new Set([
        "introduction", "intro", "overview", "basics", "fundamentals", "general",
        "miscellaneous", "others", "practical", "practicals", "theory", "lab", "labs",
        "laboratory", "project", "projects", "assignment", "assignments", "seminar",
        "workshop", "tutorial", "tutorials", "revision", "examination", "examinations",
        "test", "tests", "quiz", "quizzes", "note", "notes", "references", "textbooks",
        "syllabus", "contents", "topics", "unit", "units", "module", "modules",
        "chapter", "chapters", "part", "parts", "data", "information"
    ]);
    const adminHeading = /^(?:course\s+(?:objectives?|outcomes?|description|code|title)|program(?:me)?\s+outcomes?|learning\s+outcomes?|expected\s+outcomes?|teaching\s+scheme|examination\s+scheme|text\s*books?|reference\s+books?|recommended\s+(?:reading|books?)|required\s+reading|suggested\s+reading|further\s+reading|reading\s+list|web\s+resources|online\s+resources|faculty|instructor|contact\s+(?:details|information)|office\s+hours|academic\s+integrity|plagiarism)\b/i;

    let items = parseTextarea();
    let syncing = false;

    function parseTextarea() {
        return textarea.value
            .split("\n")
            .map((line) => line.trim())
            .filter(Boolean)
            .map((text) => ({ text, selected: true }));
    }

    function selectedTexts() {
        return items
            .filter((item) => item.selected)
            .map((item) => item.text.trim())
            .filter(Boolean);
    }

    function updateCount() {
        if (!countLabel) return;
        const selected = selectedTexts().length;
        countLabel.textContent = `${selected} of ${items.length} selected`;
        if (submitButton) submitButton.disabled = selected === 0;
    }

    function refreshDiff() {
        if (!diffList) return;
        const current = selectedTexts();
        const added = current.filter((item) => !original.includes(item));
        const removed = original.filter((item) => !current.includes(item));
        diffList.innerHTML = "";
        if (!added.length && !removed.length) {
            const li = document.createElement("li");
            li.className = "muted";
            li.textContent = "No changes yet.";
            diffList.appendChild(li);
            return;
        }
        added.forEach((item) => {
            const li = document.createElement("li");
            li.className = "diff-add";
            li.textContent = `+ ${item}`;
            diffList.appendChild(li);
        });
        removed.forEach((item) => {
            const li = document.createElement("li");
            li.className = "diff-remove";
            li.textContent = `- ${item}`;
            diffList.appendChild(li);
        });
    }

    function sync() {
        if (syncing) return;
        syncing = true;
        textarea.value = selectedTexts().join("\n");
        updateCount();
        refreshDiff();
        syncing = false;
    }

    function render() {
        list.innerHTML = "";
        items.forEach((item, index) => {
            const row = document.createElement("li");
            row.className = "topic-edit-item" + (item.selected ? "" : " is-excluded");
            row.draggable = true;

            const select = document.createElement("input");
            select.type = "checkbox";
            select.className = "topic-select";
            select.checked = item.selected;
            select.setAttribute("aria-label", `Include topic ${index + 1}`);
            select.addEventListener("change", () => {
                item.selected = select.checked;
                row.classList.toggle("is-excluded", !item.selected);
                sync();
            });

            const handle = document.createElement("span");
            handle.className = "drag-handle";
            handle.textContent = "drag";
            handle.title = "Drag to reorder";

            const input = document.createElement("input");
            input.type = "text";
            input.value = item.text;
            input.className = "topic-input";
            input.placeholder = "Add a topic or module";
            input.addEventListener("input", () => {
                item.text = input.value;
                sync();
            });
            input.addEventListener("keydown", (event) => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    addTopic(index + 1);
                }
            });

            const remove = document.createElement("button");
            remove.type = "button";
            remove.className = "topic-remove";
            remove.textContent = "Remove";
            remove.addEventListener("click", () => {
                items.splice(index, 1);
                if (!items.length) items.push({ text: "", selected: true });
                render();
                sync();
            });

            row.addEventListener("dragstart", (event) => {
                event.dataTransfer.setData("text/plain", String(index));
            });
            row.addEventListener("dragover", (event) => {
                event.preventDefault();
                row.classList.add("drag-over");
            });
            row.addEventListener("dragleave", () => row.classList.remove("drag-over"));
            row.addEventListener("drop", (event) => {
                event.preventDefault();
                row.classList.remove("drag-over");
                const from = parseInt(event.dataTransfer.getData("text/plain"), 10);
                const to = index;
                if (Number.isNaN(from) || Number.isNaN(to) || from === to) return;
                const moved = items.splice(from, 1)[0];
                items.splice(to, 0, moved);
                render();
                sync();
            });

            row.appendChild(select);
            row.appendChild(handle);
            row.appendChild(input);
            row.appendChild(remove);
            list.appendChild(row);
        });
    }

    function addTopic(position) {
        const at = typeof position === "number" ? position : items.length;
        items.splice(at, 0, { text: "", selected: true });
        render();
        sync();
        const inputs = list.querySelectorAll(".topic-input");
        const target = inputs[Math.min(at, inputs.length - 1)];
        if (target) target.focus();
    }

    function cleanTopics(topics) {
        const seen = new Set();
        const cleaned = [];
        topics.forEach((topic) => {
            let text = topic.replace(/\s+/g, " ").trim().replace(/^[,;:\-–—\s]+|[,;:\-–—\s]+$/g, "");
            if (!text || text.length < 3 || text.length > 140) return;
            if (!/[A-Za-z]{2}/.test(text)) return;
            const lower = text.toLowerCase();
            if (genericTopics.has(lower)) return;
            if (adminHeading.test(text)) return;
            if (/^(?:unit|module|chapter|week|part|section|paper)\s*(?:no\.?)?\s*[-–—:.]?\s*(?:\d{1,2}|[ivxlcdm]{1,6}|[a-z])\s*[:\-–—.]*$/i.test(text)) return;
            if (/^(?:page|pg\.?)\s*\d+/i.test(text)) return;
            if (/^\d+\s*(?:credits?|marks?|hours?|hrs?|periods?)$/i.test(text)) return;
            const key = lower.replace(/[^a-z0-9]+/g, " ").trim();
            if (!key || seen.has(key)) return;
            seen.add(key);
            cleaned.push(text);
        });
        return cleaned;
    }

    textarea.addEventListener("input", () => {
        if (syncing) return;
        items = parseTextarea();
        render();
        updateCount();
        refreshDiff();
    });

    root.querySelector("[data-topic-add]")?.addEventListener("click", () => addTopic());
    root.querySelector("[data-topic-select-all]")?.addEventListener("click", () => {
        items.forEach((item) => { item.selected = true; });
        render();
        sync();
    });
    root.querySelector("[data-topic-clear]")?.addEventListener("click", () => {
        items.forEach((item) => { item.selected = false; });
        render();
        sync();
    });
    root.querySelector("[data-topic-remove-selected]")?.addEventListener("click", () => {
        items = items.filter((item) => !item.selected);
        if (!items.length) items.push({ text: "", selected: true });
        render();
        sync();
    });
    root.querySelector("[data-topic-clean]")?.addEventListener("click", () => {
        items = cleanTopics(items.map((item) => item.text)).map((text) => ({ text, selected: true }));
        if (!items.length) items.push({ text: "", selected: true });
        render();
        sync();
    });

    render();
    updateCount();
    refreshDiff();
})();
