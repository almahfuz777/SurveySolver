(() => {
    const form = document.querySelector('.response-form');
    const rulesElement = document.getElementById('response-branch-rules');
    if (!form) return;

    const initializeRanking = (list) => {
        const selects = [...list.querySelectorAll('select')];
        if (!selects.length) return;

        const fieldName = selects[0].name;
        const choices = [...selects[0].options]
            .filter((option) => option.value)
            .map((option) => ({ id: option.value, label: option.textContent.trim() }));
        const choiceById = new Map(choices.map((choice) => [choice.id, choice]));
        const selectedIds = selects
            .map((select) => select.value)
            .filter((id, index, ids) => choiceById.has(id) && ids.indexOf(id) === index);
        const orderedChoices = [
            ...selectedIds.map((id) => choiceById.get(id)),
            ...choices.filter((choice) => !selectedIds.includes(choice.id)),
        ];
        const status = list.parentElement.querySelector('[data-ranking-status]');
        const help = list.parentElement.querySelector('[data-ranking-help]');
        let draggedItem = null;

        const announce = (message) => {
            if (status) status.textContent = message;
        };

        const syncRows = () => {
            const rows = [...list.querySelectorAll('[data-ranking-item]')];
            rows.forEach((row, index) => {
                const position = index + 1;
                const label = row.querySelector('[data-ranking-label]').textContent.trim();
                row.querySelector('[data-ranking-number]').textContent = position;
                row.querySelector('[data-ranking-up]').disabled = index === 0;
                row.querySelector('[data-ranking-down]').disabled = index === rows.length - 1;
                row.querySelector('[data-ranking-up]').setAttribute(
                    'aria-label',
                    `Move ${label} up from rank ${position}`,
                );
                row.querySelector('[data-ranking-down]').setAttribute(
                    'aria-label',
                    `Move ${label} down from rank ${position}`,
                );
            });
        };

        const moveRow = (row, direction) => {
            const sibling = direction === 'up'
                ? row.previousElementSibling
                : row.nextElementSibling;
            if (!sibling) return;
            if (direction === 'up') {
                list.insertBefore(row, sibling);
            } else {
                list.insertBefore(sibling, row);
            }
            syncRows();
            const label = row.querySelector('[data-ranking-label]').textContent.trim();
            const position = [...list.children].indexOf(row) + 1;
            announce(`${label} moved to rank ${position}.`);
            form.dispatchEvent(new Event('change', { bubbles: true }));
        };

        const rows = orderedChoices.map((choice) => {
            const row = document.createElement('div');
            row.className = 'response-rank-row response-rank-item';
            row.draggable = true;
            row.dataset.rankingItem = '';
            row.innerHTML = `
                <span class="response-rank-number" data-ranking-number></span>
                <input type="hidden" name="${fieldName}" value="${choice.id}">
                <span class="response-rank-label" data-ranking-label></span>
                <span class="response-rank-controls">
                    <span class="response-rank-grip" aria-hidden="true">
                        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                            <circle cx="9" cy="6" r="1"></circle><circle cx="15" cy="6" r="1"></circle>
                            <circle cx="9" cy="12" r="1"></circle><circle cx="15" cy="12" r="1"></circle>
                            <circle cx="9" cy="18" r="1"></circle><circle cx="15" cy="18" r="1"></circle>
                        </svg>
                    </span>
                    <button class="response-rank-move" type="button" data-ranking-up>↑</button>
                    <button class="response-rank-move" type="button" data-ranking-down>↓</button>
                </span>
            `;
            row.querySelector('[data-ranking-label]').textContent = choice.label;
            return row;
        });

        list.replaceChildren(...rows);
        list.classList.add('is-draggable');
        if (help) {
            help.textContent = 'Drag items into order, with the highest rank first. Use the arrow buttons for keyboard or touch.';
        }
        syncRows();

        list.addEventListener('click', (event) => {
            const button = event.target.closest('[data-ranking-up], [data-ranking-down]');
            if (!button) return;
            moveRow(
                button.closest('[data-ranking-item]'),
                button.hasAttribute('data-ranking-up') ? 'up' : 'down',
            );
        });
        list.addEventListener('dragstart', (event) => {
            const row = event.target.closest('[data-ranking-item]');
            if (!row) return;
            draggedItem = row;
            row.classList.add('is-dragging');
            event.dataTransfer.effectAllowed = 'move';
            event.dataTransfer.setData('text/plain', row.querySelector('input').value);
        });
        list.addEventListener('dragover', (event) => {
            if (!draggedItem) return;
            event.preventDefault();
            const target = event.target.closest('[data-ranking-item]');
            if (!target || target === draggedItem) return;
            const bounds = target.getBoundingClientRect();
            const insertBefore = event.clientY < bounds.top + bounds.height / 2;
            list.insertBefore(draggedItem, insertBefore ? target : target.nextElementSibling);
        });
        list.addEventListener('dragend', () => {
            if (!draggedItem) return;
            const label = draggedItem.querySelector('[data-ranking-label]').textContent.trim();
            draggedItem.classList.remove('is-dragging');
            syncRows();
            const position = [...list.children].indexOf(draggedItem) + 1;
            announce(`${label} moved to rank ${position}.`);
            draggedItem = null;
            form.dispatchEvent(new Event('change', { bubbles: true }));
        });
    };

    form.querySelectorAll('[data-ranking-list]').forEach(initializeRanking);

    const rules = rulesElement ? JSON.parse(rulesElement.textContent) : [];
    if (!rules.length) return;

    const sections = [...form.querySelectorAll('[data-response-section]')];
    const sectionIndexes = new Map(
        sections.map((section, index) => [section.dataset.responseSection, index]),
    );

    const normalized = (value) => value.trim().toLocaleLowerCase();

    const answerValues = (questionId) => {
        const question = form.querySelector(`[data-question-id="${questionId}"]`);
        if (!question || question.closest('[data-response-section]').hidden) return [];
        const values = [];
        question.querySelectorAll('input, select, textarea').forEach((control) => {
            if (control.disabled || ['submit', 'button'].includes(control.type)) return;
            if ((control.type === 'radio' || control.type === 'checkbox') && !control.checked) return;
            if (control.tagName === 'SELECT') {
                [...control.selectedOptions].forEach((option) => {
                    if (option.value) values.push(option.value, option.textContent);
                });
                return;
            }
            if (!control.value) return;
            values.push(control.value);
            const label = control.closest('label');
            if (label) values.push(label.textContent);
        });
        return values.map(normalized).filter(Boolean);
    };

    const matches = (rule) => {
        const values = answerValues(rule.source_question);
        if (rule.operator === 'answered') return values.length > 0;
        const comparison = normalized(rule.compare_value);
        if (rule.operator === 'equals') return values.includes(comparison);
        if (rule.operator === 'not_equals') return values.length > 0 && !values.includes(comparison);
        if (rule.operator === 'contains') return values.some((value) => value.includes(comparison));
        return false;
    };

    const setSectionAvailable = (section, available) => {
        section.hidden = !available;
        section.querySelectorAll('input, select, textarea').forEach((control) => {
            control.disabled = !available;
        });
    };

    const applyBranches = () => {
        sections.forEach((section) => setSectionAvailable(section, false));
        const visited = new Set();
        let position = 0;
        while (position < sections.length && !visited.has(position)) {
            visited.add(position);
            const section = sections[position];
            setSectionAvailable(section, true);
            const sectionRules = rules.filter(
                (rule) => rule.source_section === section.dataset.responseSection,
            );
            const rule = sectionRules.find(matches);
            if (!rule) {
                position += 1;
            } else if (rule.action === 'end_survey') {
                break;
            } else {
                position = sectionIndexes.get(rule.target_section) ?? sections.length;
            }
        }
    };

    form.addEventListener('change', applyBranches);
    form.addEventListener('input', applyBranches);
    applyBranches();
})();
