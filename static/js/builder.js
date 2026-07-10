const builder = document.querySelector('[data-builder]');

if (builder) {
    const status = document.querySelector('[data-save-status]');
    let saveQueue = Promise.resolve();
    const timers = new WeakMap();

    const updateRevision = (revision) => {
        document.querySelectorAll('input[name="revision"]').forEach((input) => {
            input.value = revision;
        });
    };

    const showErrors = (form, errors = {}) => {
        form.querySelectorAll('[data-errors-for]').forEach((container) => {
            const fieldErrors = errors[container.dataset.errorsFor] || [];
            container.textContent = fieldErrors.map((error) => error.message).join(' ');
        });
    };

    const saveForm = async (form) => {
        status.textContent = 'Saving…';
        const response = await fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: {'Accept': 'application/json'},
        });
        const result = await response.json();
        if (!response.ok) {
            showErrors(form, result.errors);
            status.textContent = result.error || 'Check the highlighted settings';
            if (response.status === 409) status.classList.add('has-conflict');
            return;
        }
        showErrors(form);
        updateRevision(result.revision);
        status.classList.remove('has-conflict');
        status.textContent = 'All changes saved';
    };

    document.querySelectorAll('.autosave-form').forEach((form) => {
        form.addEventListener('input', () => {
            status.textContent = 'Unsaved changes';
            clearTimeout(timers.get(form));
            timers.set(form, setTimeout(() => {
                saveQueue = saveQueue.then(() => saveForm(form));
            }, 700));
        });
        form.addEventListener('change', () => {
            clearTimeout(timers.get(form));
            saveQueue = saveQueue.then(() => saveForm(form));
        });
        form.addEventListener('submit', (event) => event.preventDefault());
    });

    window.addEventListener('beforeunload', (event) => {
        if (status.textContent === 'Unsaved changes' || status.textContent === 'Saving…') {
            event.preventDefault();
        }
    });
}
