const builder = document.querySelector('[data-builder]');

if (builder) {
    const statusEl = document.querySelector('[data-save-status]');
    const statusText = statusEl ? statusEl.querySelector('[data-save-text]') : null;
    const selectedCard = document.querySelector('[data-selected-card]');
    const inspector = document.querySelector('[data-inspector]');
    const rail = document.querySelector('[data-rail]');
    const editorForm = document.querySelector('.question-autosave');

    const CHOICE_TYPES = ['single_choice', 'multiple_choice', 'dropdown', 'ranking', 'likert_matrix'];
    const GRIP_SVG = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M4 9h16"/><path d="M4 15h16"/></svg>';

    let saveQueue = Promise.resolve();
    const timers = new WeakMap();
    let editSeq = 0;
    let savedSeq = 0;
    let saving = 0;
    let pendingReload = false;
    let intentionalNav = false;

    // ---------- Save status ----------

    const setStatus = (state, text) => {
        if (!statusEl) return;
        statusEl.classList.remove('is-dirty', 'is-saving', 'is-error');
        if (state) statusEl.classList.add(state);
        if (state !== 'is-error') statusEl.classList.remove('has-conflict');
        statusText.textContent = text;
    };

    const isDirty = () => editSeq > savedSeq;

    // ---------- Autosave core ----------

    const updateRevision = (revision) => {
        document.querySelectorAll('input[name="revision"]').forEach((input) => {
            input.value = revision;
        });
    };

    const showErrors = (form, errors = {}) => {
        form.querySelectorAll('[data-errors-for]').forEach((container) => {
            const name = container.dataset.errorsFor;
            const fieldErrors = errors[name] || [];
            container.textContent = fieldErrors.map((error) => error.message).join(' ');
            const field = form.querySelector(`[name="${name}"]`);
            if (field) field.classList.toggle('has-error', fieldErrors.length > 0);
        });
    };

    const saveForm = async (form) => {
        const seq = editSeq;
        saving += 1;
        setStatus('is-saving', 'Saving…');
        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: new FormData(form),
                headers: {'Accept': 'application/json'},
            });
            const result = await response.json();
            if (!response.ok) {
                pendingReload = false;
                showErrors(form, result.errors);
                setStatus('is-error', result.error || 'Check the highlighted settings');
                if (response.status === 409) statusEl.classList.add('has-conflict');
                return;
            }
            showErrors(form);
            if (result.revision) updateRevision(result.revision);
            savedSeq = Math.max(savedSeq, seq);
            if (pendingReload && form === editorForm) {
                intentionalNav = true;
                window.location.reload();
                return;
            }
            if (!isDirty()) {
                const time = new Date().toLocaleTimeString([], {hour: 'numeric', minute: '2-digit'});
                setStatus('', `Saved · ${time}`);
            }
        } catch (error) {
            pendingReload = false;
            setStatus('is-error', 'Offline — changes not saved');
        } finally {
            saving -= 1;
        }
    };

    document.querySelectorAll('.autosave-form').forEach((form) => {
        form.addEventListener('input', () => {
            editSeq += 1;
            setStatus('is-dirty', 'Unsaved changes');
            clearTimeout(timers.get(form));
            timers.set(form, setTimeout(() => {
                saveQueue = saveQueue.then(() => saveForm(form));
            }, 700));
        });
        form.addEventListener('change', () => {
            editSeq += 1;
            clearTimeout(timers.get(form));
            saveQueue = saveQueue.then(() => saveForm(form));
        });
        form.addEventListener('submit', (event) => event.preventDefault());
    });

    // ---------- Choice/statement row editors ----------

    const glyphFor = (type) => {
        if (type === 'single_choice') return 'radio';
        if (type === 'multiple_choice') return 'check';
        if (type === 'ranking') return 'rank';
        return null;
    };

    const editors = [];

    document.querySelectorAll('[data-choice-editor]').forEach((container) => {
        const textarea = container.querySelector('textarea');
        if (!textarea) return;
        const itemName = container.dataset.itemName || 'option';
        textarea.hidden = true;

        const rows = document.createElement('div');
        rows.className = 'choice-rows';
        const addButton = document.createElement('button');
        addButton.type = 'button';
        addButton.className = 'choice-add';
        addButton.textContent = `+ Add ${itemName}`;
        container.append(rows, addButton);

        const sync = () => {
            textarea.value = [...rows.querySelectorAll('input')]
                .map((input) => input.value.trim())
                .filter(Boolean)
                .join('\n');
        };

        const triggerSave = () => {
            textarea.dispatchEvent(new Event('change', {bubbles: true}));
        };

        const renumber = () => {
            rows.querySelectorAll('.choice-glyph-rank').forEach((badge, index) => {
                badge.textContent = index + 1;
            });
        };

        const makeRow = (value) => {
            const row = document.createElement('div');
            row.className = 'choice-row';
            const input = document.createElement('input');
            input.type = 'text';
            input.value = value;
            input.placeholder = `New ${itemName}`;
            input.setAttribute('aria-label', itemName);
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'choice-remove';
            remove.setAttribute('aria-label', `Remove ${itemName}`);
            remove.innerHTML = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" aria-hidden="true"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>';
            const dropRow = () => {
                row.remove();
                if (!rows.children.length) rows.append(makeRow(''));
                renumber();
                sync();
                triggerSave();
            };
            remove.addEventListener('click', dropRow);
            input.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    const next = makeRow('');
                    row.after(next);
                    renumber();
                    next.querySelector('input').focus();
                } else if (event.key === 'Backspace' && input.value === '' && rows.children.length > 1) {
                    event.preventDefault();
                    const neighbour = row.previousElementSibling || row.nextElementSibling;
                    dropRow();
                    if (neighbour) neighbour.querySelector('input').focus();
                } else if (event.altKey && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
                    event.preventDefault();
                    const sibling = event.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling;
                    if (sibling) {
                        if (event.key === 'ArrowUp') sibling.before(row); else sibling.after(row);
                        renumber();
                        sync();
                        triggerSave();
                        input.focus();
                    }
                }
            });
            row.append(input, remove);
            return row;
        };

        const api = {
            container,
            itemName,
            values: () => [...rows.querySelectorAll('input')].map((i) => i.value.trim()).filter(Boolean),
            setValues: (list) => {
                rows.textContent = '';
                list.forEach((label) => rows.append(makeRow(label)));
                if (!rows.children.length) rows.append(makeRow(''), makeRow(''));
                api.refreshGlyphs();
                sync();
            },
            refreshGlyphs: () => {
                const type = editorForm ? editorForm.querySelector('select[name="type"]').value : '';
                const glyph = itemName === 'option' ? glyphFor(type) : null;
                rows.querySelectorAll('.choice-row').forEach((row, index) => {
                    let badge = row.querySelector('.choice-glyph, .rv-glyph, .rv-ranknum');
                    if (badge) badge.remove();
                    if (!glyph) return;
                    if (glyph === 'rank') {
                        badge = document.createElement('span');
                        badge.className = 'rv-ranknum choice-glyph-rank';
                        badge.textContent = index + 1;
                    } else {
                        badge = document.createElement('span');
                        badge.className = `rv-glyph rv-glyph-${glyph === 'check' ? 'check' : 'radio'}`;
                    }
                    row.prepend(badge);
                });
            },
        };
        editors.push(api);

        textarea.value.split('\n').map((line) => line.trim()).filter(Boolean)
            .forEach((line) => rows.append(makeRow(line)));
        if (!rows.children.length) {
            rows.append(makeRow(''), makeRow(''));
        }
        api.refreshGlyphs();

        // Row typing bubbles to the form's autosave listener; keep the
        // textarea current before the debounce reads the form data.
        rows.addEventListener('input', sync);
        addButton.addEventListener('click', () => {
            const row = makeRow('');
            rows.append(row);
            api.refreshGlyphs();
            row.querySelector('input').focus();
        });
    });

    const optionsEditor = editors.find((e) => e.itemName === 'option') || null;
    const rowsEditor = editors.find((e) => e.itemName === 'statement') || null;

    // ---------- Type-conditional config visibility ----------

    let typeSelect = null;
    if (editorForm) {
        typeSelect = editorForm.querySelector('select[name="type"]');

        const applyTypeVisibility = () => {
            const type = typeSelect.value;
            document.querySelectorAll('[data-config-for]').forEach((group) => {
                group.classList.toggle('is-hidden', !group.dataset.configFor.split(' ').includes(type));
            });
            const choiceLabel = document.querySelector('[data-choice-label]');
            if (choiceLabel) {
                choiceLabel.textContent = type === 'likert_matrix'
                    ? choiceLabel.dataset.labelLikert
                    : choiceLabel.dataset.labelDefault;
            }
            if (optionsEditor) optionsEditor.refreshGlyphs();
        };

        const seedDefaults = (type) => {
            if (CHOICE_TYPES.includes(type) && optionsEditor && optionsEditor.values().length < 2) {
                optionsEditor.setValues(type === 'likert_matrix'
                    ? ['Strongly disagree', 'Disagree', 'Neutral', 'Agree', 'Strongly agree']
                    : ['Option 1', 'Option 2']);
            }
            if (type === 'likert_matrix' && rowsEditor && rowsEditor.values().length < 2) {
                rowsEditor.setValues(['Statement 1', 'Statement 2']);
            }
        };

        // Switching type re-renders the responder view server-side once the
        // save lands; seed sensible defaults first so validation cannot fail
        // mid-flow with an empty option list.
        typeSelect.addEventListener('change', () => {
            seedDefaults(typeSelect.value);
            applyTypeVisibility();
            pendingReload = true;
        });
        applyTypeVisibility();
    }

    // ---------- Live mirroring into the selected responder card ----------

    const el = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };

    const mirror = selectedCard && editorForm ? {
        prompt: selectedCard.querySelector('[data-mirror="prompt"]'),
        required: selectedCard.querySelector('[data-mirror="required"]'),
        help: selectedCard.querySelector('[data-mirror="help"]'),
        body: selectedCard.querySelector('[data-mirror="body"]'),
    } : null;

    const configValue = (name) => {
        const field = editorForm.querySelector(`[name="${name}"]`);
        return field ? field.value.trim() : '';
    };

    // Editing an option label directly in the center card re-renders the
    // whole list on the next keystroke via scheduleMirror; skip that rebuild
    // while focus is inside it so we don't blow away the caret mid-edit.
    const editingCenterOption = () => document.activeElement && document.activeElement.dataset && document.activeElement.dataset.optIndex !== undefined;

    const wireOptionLabel = (label, index) => {
        label.dataset.optIndex = String(index);
        label.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') event.preventDefault();
        });
        label.addEventListener('paste', (event) => {
            event.preventDefault();
            const text = (event.clipboardData || window.clipboardData).getData('text/plain');
            document.execCommand('insertText', false, text);
        });
        label.addEventListener('input', () => {
            if (!optionsEditor) return;
            const rowInput = optionsEditor.container.querySelectorAll('.choice-row input')[index];
            if (!rowInput) return;
            rowInput.value = label.textContent;
            rowInput.dispatchEvent(new Event('input', {bubbles: true}));
        });
    };

    if (mirror && mirror.body) {
        mirror.body.querySelectorAll('[data-opt-index]').forEach((label) => {
            wireOptionLabel(label, Number(label.dataset.optIndex));
        });
    }

    const rebuildBody = () => {
        if (!mirror || !mirror.body || pendingReload || editingCenterOption()) return;
        const type = typeSelect.value;
        const body = mirror.body;

        if (type === 'single_choice' || type === 'multiple_choice' || type === 'ranking') {
            body.textContent = '';
            if (type === 'ranking') body.append(el('p', 'rv-note', 'Drag to reorder — most important at the top'));
            const list = el('div', 'rv-options');
            const values = optionsEditor ? optionsEditor.values() : [];
            values.forEach((label, index) => {
                const opt = el('span', type === 'ranking' ? 'rv-opt rv-opt-rank' : 'rv-opt');
                const labelEl = el('span', 'rv-opt-label', label);
                labelEl.setAttribute('contenteditable', 'true');
                labelEl.setAttribute('role', 'textbox');
                labelEl.setAttribute('aria-label', `Option ${index + 1}`);
                wireOptionLabel(labelEl, index);
                if (type === 'ranking') {
                    opt.append(el('span', 'rv-ranknum', index + 1));
                    opt.append(labelEl);
                    opt.append(el('span', 'rv-spacer'));
                    const grip = el('span');
                    grip.innerHTML = GRIP_SVG;
                    opt.append(grip.firstChild);
                } else {
                    opt.append(el('span', `rv-glyph rv-glyph-${type === 'multiple_choice' ? 'check' : 'radio'}`));
                    opt.append(labelEl);
                }
                list.append(opt);
            });
            if (!values.length) {
                const opt = el('span', 'rv-opt rv-opt-placeholder', 'Add options in the editor');
                list.prepend(opt);
            }
            body.append(list);
        } else if (type === 'likert_matrix') {
            const cols = optionsEditor ? optionsEditor.values() : [];
            const rows = rowsEditor ? rowsEditor.values() : [];
            body.textContent = '';
            const scroll = el('div', 'rv-matrix-scroll');
            const grid = el('div', 'rv-matrix');
            grid.style.setProperty('--matrix-cols', Math.max(cols.length, 1));
            grid.append(el('span', 'rv-matrix-corner'));
            cols.forEach((label) => grid.append(el('span', 'rv-matrix-col', label)));
            rows.forEach((label) => {
                grid.append(el('span', 'rv-matrix-row', label));
                cols.forEach(() => {
                    const cell = el('span', 'rv-matrix-cell');
                    cell.append(el('span', 'rv-glyph rv-glyph-radio'));
                    grid.append(cell);
                });
            });
            scroll.append(grid);
            body.append(scroll);
        } else if (type === 'scale') {
            const min = parseInt(configValue('scale_min') || '1', 10);
            const max = parseInt(configValue('scale_max') || '5', 10);
            body.textContent = '';
            const wrap = el('div', 'rv-scale');
            const points = el('div', 'rv-scale-points');
            if (Number.isFinite(min) && Number.isFinite(max) && max >= min) {
                for (let p = min; p <= Math.min(max, min + 19); p += 1) {
                    points.append(el('span', 'rv-scale-pt', p));
                }
            }
            wrap.append(points);
            const low = configValue('scale_min_label');
            const high = configValue('scale_max_label');
            if (low || high) {
                const labels = el('div', 'rv-scale-labels');
                labels.append(el('span', '', low), el('span', '', high));
                wrap.append(labels);
            }
            body.append(wrap);
        } else if (type === 'long_text') {
            body.textContent = '';
            const field = el('span', 'rv-field rv-field-area');
            field.append(el('span', 'rv-placeholder', 'Share as much detail as you like…'));
            body.append(field);
            const maxLength = configValue('max_length');
            if (maxLength) body.append(el('div', 'rv-count', `0 / ${maxLength}`));
        }
    };

    if (mirror) {
        let mirrorTimer;
        const scheduleMirror = () => {
            clearTimeout(mirrorTimer);
            mirrorTimer = setTimeout(rebuildBody, 120);
        };

        const promptField = editorForm.querySelector('[name="prompt"]');
        promptField.addEventListener('input', () => {
            if (document.activeElement === mirror.prompt) return;
            mirror.prompt.textContent = promptField.value.trim() || 'Untitled question';
        });
        const helpField = editorForm.querySelector('[name="help_text"]');
        helpField.addEventListener('input', () => {
            if (document.activeElement === mirror.help) return;
            const value = helpField.value.trim();
            mirror.help.textContent = value;
            mirror.help.hidden = !value;
        });

        // Center-column editing: typing directly in the responder-view card
        // writes back into the inspector field and rides its existing
        // autosave debounce, so both surfaces stay in sync either way.
        const wireCenterTextMirror = (centerEl, field) => {
            if (!centerEl || !field) return;
            centerEl.addEventListener('keydown', (event) => {
                if (event.key === 'Enter') event.preventDefault();
            });
            centerEl.addEventListener('paste', (event) => {
                event.preventDefault();
                const text = (event.clipboardData || window.clipboardData).getData('text/plain');
                document.execCommand('insertText', false, text);
            });
            centerEl.addEventListener('input', () => {
                field.value = centerEl.textContent;
                field.dispatchEvent(new Event('input', {bubbles: true}));
            });
            centerEl.addEventListener('blur', () => {
                const value = field.value.trim();
                centerEl.textContent = value || (centerEl === mirror.prompt ? 'Untitled question' : '');
                if (centerEl === mirror.help) centerEl.hidden = !value;
            });
        };
        wireCenterTextMirror(mirror.prompt, promptField);
        wireCenterTextMirror(mirror.help, helpField);
        const requiredField = editorForm.querySelector('[name="required"]');
        requiredField.addEventListener('change', () => {
            mirror.required.hidden = !requiredField.checked;
        });
        editors.forEach((api) => api.container.addEventListener('input', scheduleMirror));
        ['scale_min', 'scale_max', 'scale_min_label', 'scale_max_label', 'max_length'].forEach((name) => {
            const field = editorForm.querySelector(`[name="${name}"]`);
            if (field) field.addEventListener('input', scheduleMirror);
        });
    }

    // ---------- Canvas question toolbar toggles ----------
    // Mirror the in-canvas Required/Shuffle switches to the inspector's real
    // form fields so they ride the existing autosave debounce, and reflect
    // inspector-side changes back onto the canvas switches.
    if (editorForm) {
        const linkToggle = (canvasSelector, fieldName) => {
            const canvas = document.querySelector(canvasSelector);
            const field = editorForm.querySelector(`[name="${fieldName}"]`);
            if (!canvas || !field) return;
            canvas.addEventListener('change', () => {
                if (field.checked === canvas.checked) return;
                field.checked = canvas.checked;
                field.dispatchEvent(new Event('change', {bubbles: true}));
            });
            field.addEventListener('change', () => { canvas.checked = field.checked; });
        };
        linkToggle('[data-canvas-required]', 'required');
        linkToggle('[data-canvas-shuffle]', 'randomize_choices');
    }

    // ---------- Branch rule editor ----------
    const branchForm = document.querySelector('[data-logic-form]');
    if (branchForm) {
        // "Is answered" needs no comparison value; only "go to section" needs a
        // target section. Hide each conditional field when it doesn't apply.
        const toggleField = (control, field, showWhen) => {
            if (!control || !field) return;
            const sync = () => { field.style.display = control.value === showWhen ? '' : 'none'; };
            control.addEventListener('change', sync);
            sync();
        };
        const invert = (control, field, hideWhen) => {
            if (!control || !field) return;
            const sync = () => { field.style.display = control.value === hideWhen ? 'none' : ''; };
            control.addEventListener('change', sync);
            sync();
        };
        invert(branchForm.querySelector('[data-branch-operator]'), branchForm.querySelector('[data-branch-value]'), 'answered');
        toggleField(branchForm.querySelector('[data-branch-action]'), branchForm.querySelector('[data-branch-target]'), 'go_to_section');
    }

    // ---------- Branching logic add toggle ----------
    // The branching section is always visible; the "+" reveals its add form.
    const logicAdd = document.querySelector('[data-logic-add]');
    if (logicAdd && branchForm) {
        logicAdd.addEventListener('click', () => {
            const willOpen = branchForm.hidden;
            branchForm.hidden = !willOpen;
            logicAdd.setAttribute('aria-expanded', String(willOpen));
            if (willOpen) {
                const firstField = branchForm.querySelector('select, input[type="text"]');
                if (firstField) firstField.focus({preventScroll: true});
                branchForm.scrollIntoView({block: 'nearest', behavior: 'smooth'});
            }
        });
    }

    // ---------- Add-question popover ----------

    const addToggle = document.querySelector('[data-add-toggle]');
    const addPopover = document.querySelector('[data-add-popover]');
    if (addToggle && addPopover) {
        const closePopover = () => {
            addPopover.hidden = true;
            addToggle.setAttribute('aria-expanded', 'false');
        };
        addToggle.addEventListener('click', (event) => {
            event.stopPropagation();
            const willOpen = addPopover.hidden;
            addPopover.hidden = !willOpen;
            addToggle.setAttribute('aria-expanded', String(willOpen));
        });
        document.addEventListener('click', (event) => {
            if (!addPopover.hidden && !addPopover.contains(event.target) && event.target !== addToggle) closePopover();
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !addPopover.hidden) closePopover();
        });
    }

    // ---------- Auto-growing textareas ----------

    if (editorForm) {
        const autoGrow = (el) => {
            el.style.height = 'auto';
            el.style.height = `${el.scrollHeight}px`;
        };
        editorForm.querySelectorAll('textarea[name="prompt"], textarea[name="help_text"]').forEach((textarea) => {
            autoGrow(textarea);
            textarea.addEventListener('input', () => autoGrow(textarea));
        });
    }

    // ---------- Confirmations (in-page modal, not the native browser dialog) ----------

    const confirmModal = (() => {
        let overlay, textEl, okBtn, cancelBtn, resolver, lastFocus;
        const build = () => {
            overlay = document.createElement('div');
            overlay.className = 'confirm-modal-overlay';
            overlay.innerHTML =
                '<div class="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="confirm-modal-text">' +
                    '<p class="confirm-modal-text" id="confirm-modal-text"></p>' +
                    '<div class="confirm-modal-actions">' +
                        '<button type="button" class="button button-secondary button-small" data-confirm-cancel>Cancel</button>' +
                        '<button type="button" class="button button-danger button-small" data-confirm-ok>Delete</button>' +
                    '</div>' +
                '</div>';
            document.body.append(overlay);
            textEl = overlay.querySelector('.confirm-modal-text');
            okBtn = overlay.querySelector('[data-confirm-ok]');
            cancelBtn = overlay.querySelector('[data-confirm-cancel]');
            const close = (result) => {
                overlay.classList.remove('is-open');
                if (lastFocus) lastFocus.focus();
                if (resolver) { const r = resolver; resolver = null; r(result); }
            };
            okBtn.addEventListener('click', () => close(true));
            cancelBtn.addEventListener('click', () => close(false));
            overlay.addEventListener('click', (event) => { if (event.target === overlay) close(false); });
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape' && overlay.classList.contains('is-open')) close(false);
            });
        };
        return (message) => {
            if (!overlay) build();
            textEl.textContent = message;
            lastFocus = document.activeElement;
            overlay.classList.add('is-open');
            cancelBtn.focus();
            return new Promise((resolve) => { resolver = resolve; });
        };
    })();

    document.querySelectorAll('form[data-confirm]').forEach((form) => {
        form.addEventListener('submit', (event) => {
            if (form.dataset.confirmBypass === 'true') { delete form.dataset.confirmBypass; return; }
            event.preventDefault();
            confirmModal(form.dataset.confirm).then((ok) => {
                if (!ok) return;
                form.dataset.confirmBypass = 'true';
                if (form.requestSubmit) form.requestSubmit(); else form.submit();
            });
        });
    });

    // ---------- Mobile drawers (structure rail + inspector) ----------
    // On small screens the rail and inspector collapse into slide-in panels.
    // A shared backdrop dims the canvas; only one drawer is open at a time.

    (() => {
        const railToggle = document.querySelector('[data-rail-toggle]');
        const railClose = document.querySelector('[data-rail-close]');
        const inspectorClose = document.querySelector('[data-inspector-close]');
        if (!rail && !inspector) return;

        const backdrop = document.createElement('div');
        backdrop.className = 'studio-backdrop';
        backdrop.setAttribute('hidden', '');
        document.body.append(backdrop);

        const railDrawer = window.matchMedia('(max-width: 1080px)');
        const inspectorDrawer = window.matchMedia('(max-width: 900px)');

        const syncBackdrop = () => {
            const open = (rail && rail.classList.contains('is-open')) ||
                (inspector && inspector.classList.contains('is-open'));
            backdrop.classList.toggle('is-open', open);
            backdrop.toggleAttribute('hidden', !open);
            document.body.classList.toggle('studio-drawer-open', open);
        };
        const closeRail = () => {
            if (rail) rail.classList.remove('is-open');
            if (railToggle) railToggle.setAttribute('aria-expanded', 'false');
            syncBackdrop();
        };
        const openRail = () => {
            if (!rail) return;
            if (inspector) inspector.classList.remove('is-open');
            rail.classList.add('is-open');
            if (railToggle) railToggle.setAttribute('aria-expanded', 'true');
            syncBackdrop();
        };
        const closeInspector = () => {
            if (inspector) inspector.classList.remove('is-open');
            syncBackdrop();
        };
        const openInspector = () => {
            if (!inspector) return;
            closeRail();
            inspector.classList.add('is-open');
            syncBackdrop();
        };
        const closeAll = () => { closeRail(); closeInspector(); };

        if (railToggle) railToggle.addEventListener('click', () => {
            if (rail && rail.classList.contains('is-open')) closeRail(); else openRail();
        });
        if (railClose) railClose.addEventListener('click', closeRail);
        if (inspectorClose) inspectorClose.addEventListener('click', closeInspector);
        document.querySelectorAll('[data-inspector-open]').forEach((btn) => btn.addEventListener('click', openInspector));
        backdrop.addEventListener('click', closeAll);
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') closeAll();
        });

        // Tapping a question navigates (full reload) with ?question=… ; when the
        // page comes back on a small screen, slide the inspector in so its
        // settings are immediately reachable. A default selection (no explicit
        // ?question in the URL) must not cover the canvas on arrival.
        const cameFromTap = new URLSearchParams(window.location.search).has('question');
        if (inspectorDrawer.matches && selectedCard && cameFromTap) openInspector();

        // Leaving drawer widths must reset transient state so the desktop grid
        // shows both panels normally.
        const onWidthChange = () => {
            if (!railDrawer.matches) closeRail();
            if (!inspectorDrawer.matches) closeInspector();
        };
        if (railDrawer.addEventListener) {
            railDrawer.addEventListener('change', onWidthChange);
            inspectorDrawer.addEventListener('change', onWidthChange);
        }
    })();

    // ---------- Selection scroll continuity ----------

    const scrollKey = `builder-scroll-${builder.dataset.surveyId || ''}`;
    document.querySelectorAll('a[data-select]').forEach((link) => {
        link.addEventListener('click', () => {
            try {
                sessionStorage.setItem(scrollKey, JSON.stringify({
                    y: window.scrollY,
                    rail: rail ? rail.scrollTop : 0,
                }));
            } catch (error) { /* storage unavailable — selection still works */ }
        });
    });
    let restored = false;
    try {
        const stored = sessionStorage.getItem(scrollKey);
        if (stored && new URLSearchParams(window.location.search).has('question')) {
            sessionStorage.removeItem(scrollKey);
            const position = JSON.parse(stored);
            restored = true;
            requestAnimationFrame(() => {
                window.scrollTo(0, position.y);
                if (rail) rail.scrollTop = position.rail;
            });
        }
    } catch (error) { /* ignore malformed storage */ }
    if (!restored && selectedCard && !window.location.hash) {
        selectedCard.scrollIntoView({block: 'center'});
    }

    // ---------- Rail drag-and-drop reordering ----------

    if (rail) {
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        const reorderTemplate = builder.dataset.reorderUrl || '';
        const PLACEHOLDER = '00000000-0000-0000-0000-000000000000';
        let dragRow = null;
        let originSection = null;
        let originNext = null;

        const sectionOf = (node) => node.closest('[data-rail-section]');

        // Find the row the dragged item should sit *before* for a given pointer
        // Y within a section; null means "past the last row" (append).
        const rowBefore = (section, y) => {
            const rows = [...section.querySelectorAll('.rail-q-row:not(.is-dragging)')];
            for (const row of rows) {
                const box = row.getBoundingClientRect();
                if (y < box.top + box.height / 2) return row;
            }
            return null;
        };

        const submitReorder = (questionId, sectionId, position) => {
            if (!csrfInput || !reorderTemplate) return;
            const revision = document.querySelector('input[name="revision"]');
            const form = document.createElement('form');
            form.method = 'post';
            form.action = reorderTemplate.replace(PLACEHOLDER, questionId);
            const add = (name, value) => {
                const input = document.createElement('input');
                input.type = 'hidden';
                input.name = name;
                input.value = value;
                form.append(input);
            };
            add('csrfmiddlewaretoken', csrfInput.value);
            add('revision', revision ? revision.value : '');
            add('section_id', sectionId);
            add('position', position);
            intentionalNav = true;
            document.body.append(form);
            form.submit();
        };

        rail.querySelectorAll('.rail-q-row').forEach((row) => {
            row.setAttribute('draggable', 'true');
            const link = row.querySelector('.rail-q');
            if (link) link.setAttribute('draggable', 'false');
            row.addEventListener('dragstart', (event) => {
                dragRow = row;
                originSection = sectionOf(row);
                originNext = row.nextElementSibling;
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', row.dataset.questionId);
                requestAnimationFrame(() => row.classList.add('is-dragging'));
            });
            row.addEventListener('dragend', () => {
                row.classList.remove('is-dragging');
                rail.querySelectorAll('[data-rail-section]').forEach((s) => s.classList.remove('is-drop-target'));
                dragRow = null;
            });
        });

        rail.querySelectorAll('[data-rail-section]').forEach((section) => {
            section.addEventListener('dragover', (event) => {
                if (!dragRow) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
                rail.querySelectorAll('[data-rail-section]').forEach((s) => s.classList.toggle('is-drop-target', s === section));
                const reference = rowBefore(section, event.clientY);
                if (reference) section.insertBefore(dragRow, reference);
                else section.append(dragRow);
            });
        });

        rail.addEventListener('drop', (event) => {
            if (!dragRow) return;
            event.preventDefault();
            const section = sectionOf(dragRow);
            const rows = [...section.querySelectorAll('.rail-q-row')];
            const position = rows.indexOf(dragRow);
            // Skip a no-op drop (same slot) so we don't burn a revision/reload.
            if (section === originSection && dragRow.nextElementSibling === originNext) return;
            submitReorder(dragRow.dataset.questionId, section.dataset.sectionId, position);
        });
    }

    // ---------- Unsaved-changes guard ----------

    window.addEventListener('beforeunload', (event) => {
        if (intentionalNav) return;
        if (isDirty() || saving > 0) event.preventDefault();
    });
}
