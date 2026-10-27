(function () {
    const form = document.querySelector("[data-nl-parser]");
    if (!form) return;

    const textarea = form.querySelector("[data-nl-text]");
    const parseButton = form.querySelector("[data-nl-parse]");
    const status = form.querySelector("[data-nl-status]");
    const chips = form.querySelector("[data-nl-chips]");
    const notes = form.querySelector("[data-nl-notes]");
    const typeTouched = form.querySelector("[data-nl-type-touched]");
    const typeSelect = form.querySelector('select[name="roadmap_type"]');
    if (!textarea || !parseButton) return;

    const fields = {
        title: form.querySelector('input[name="title"]'),
        plan_days: form.querySelector('input[name="plan_days"]'),
        hours_per_day: form.querySelector('input[name="hours_per_day"]'),
        study_days_per_week: form.querySelector('input[name="study_days_per_week"]'),
        current_level: form.querySelector('select[name="current_level"]'),
        pace_mode: form.querySelector('select[name="pace_mode"]'),
        target_outcome: form.querySelector('input[name="target_outcome"]'),
        weak_areas: form.querySelector('input[name="weak_areas"]'),
    };

    const initial = {};
    Object.entries(fields).forEach(([key, field]) => {
        if (field) initial[key] = field.value;
    });
    if (typeSelect) initial.roadmap_type = typeSelect.value;
    const lastApplied = {};

    let typeChangedByUser = false;
    if (typeSelect) {
        typeSelect.addEventListener("change", () => {
            typeChangedByUser = true;
            if (typeTouched) typeTouched.value = "1";
        });
    }

    function setStatus(message, tone) {
        if (!status) return;
        status.textContent = message || "";
        status.classList.toggle("is-ok", tone === "ok");
        status.classList.toggle("is-error", tone === "error");
    }

    function setValue(key, value) {
        const field = fields[key];
        if (!field || value === undefined || value === null || value === "") return false;
        if (field.type === "number" && Number(value) === 0) return false;
        const current = String(field.value).trim();
        const baseline = String(initial[key] || "").trim();
        const previous = Object.prototype.hasOwnProperty.call(lastApplied, key)
            ? String(lastApplied[key]).trim()
            : null;
        if (current !== baseline && current !== previous) return false;
        const next = String(value);
        if (field.value === next) return false;
        if (field.tagName === "SELECT") {
            const option = Array.from(field.options).some((item) => item.value === next);
            if (!option) return false;
        }
        field.value = next;
        lastApplied[key] = next;
        return true;
    }

    function renderChips(items) {
        if (!chips) return;
        chips.innerHTML = "";
        (items || []).forEach((item, index) => {
            const li = document.createElement("li");
            li.className = "nl-chip" + (index === 0 ? " is-primary" : "");
            li.textContent = item;
            chips.appendChild(li);
        });
        chips.hidden = !(items || []).length;
    }

    function renderNotes(items) {
        if (!notes) return;
        notes.innerHTML = "";
        (items || []).forEach((note) => {
            const p = document.createElement("p");
            p.textContent = note;
            notes.appendChild(p);
        });
        notes.hidden = !(items || []).length;
    }

    function applyPlan(data) {
        let filled = 0;
        const orderedKeys = [
            "title",
            "plan_days",
            "hours_per_day",
            "study_days_per_week",
            "current_level",
            "pace_mode",
            "target_outcome",
            "weak_areas",
        ];
        orderedKeys.forEach((key) => {
            if (setValue(key, data[key])) filled += 1;
        });
        if (
            typeSelect
            && !typeChangedByUser
            && data.roadmap_type
            && (
                typeSelect.value === initial.roadmap_type
                || typeSelect.value === lastApplied.roadmap_type
            )
            && typeSelect.value !== data.roadmap_type
        ) {
            typeSelect.value = data.roadmap_type;
            lastApplied.roadmap_type = data.roadmap_type;
            filled += 1;
        }
        return filled;
    }

    async function parseSentence() {
        const text = textarea.value.trim();
        if (!text) {
            setStatus("Describe your plan first.", "error");
            textarea.focus();
            return;
        }
        const url = form.dataset.parseUrl;
        if (!url) {
            setStatus("Natural-language fill is unavailable right now.", "error");
            return;
        }

        parseButton.disabled = true;
        setStatus("Reading your sentence...");
        try {
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8" },
                body: new URLSearchParams({ nl_input: text }),
                credentials: "same-origin",
            });
            const contentType = response.headers.get("content-type") || "";
            if (!contentType.includes("application/json")) {
                setStatus("Please refresh the page and log in again.", "error");
                return;
            }
            const data = await response.json();
            if (!response.ok) {
                setStatus(data.error || "We couldn't read that sentence.", "error");
                return;
            }

            renderChips(data.summary);
            renderNotes(data.notes);

            if (!data.understood) {
                setStatus("No plan found yet. Add a goal, timeline, hours, or topics.", "error");
                return;
            }

            const filled = applyPlan(data);
            if (filled) {
                setStatus("Plan understood. Review the filled fields below.", "ok");
            } else {
                setStatus("Plan understood. Your existing values were kept.", "ok");
            }
        } catch (error) {
            setStatus("We couldn't reach the planner. Check your connection and try again.", "error");
        } finally {
            parseButton.disabled = false;
        }
    }

    parseButton.addEventListener("click", parseSentence);
    textarea.addEventListener("keydown", (event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
            event.preventDefault();
            parseSentence();
        }
    });

    form.querySelectorAll("[data-nl-example]").forEach((button) => {
        button.addEventListener("click", () => {
            textarea.value = button.dataset.nlExample || "";
            parseSentence();
        });
    });
})();
