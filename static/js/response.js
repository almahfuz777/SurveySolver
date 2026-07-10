(() => {
    const form = document.querySelector('.response-form');
    const rulesElement = document.getElementById('response-branch-rules');
    if (!form || !rulesElement) return;

    const rules = JSON.parse(rulesElement.textContent);
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
