document.addEventListener('DOMContentLoaded', () => {
    const tabList = document.querySelector('.response-view-tabs');
    if (!tabList) return;

    const tabs = Array.from(tabList.querySelectorAll('[role="tab"]'));
    const panels = Array.from(document.querySelectorAll('.response-view-panel'));
    const requests = {};
    const debounceTimers = {};

    const activateView = (tab, moveFocus = false) => {
        const panelId = tab.getAttribute('aria-controls');
        tabs.forEach((candidate) => {
            const isActive = candidate === tab;
            candidate.classList.toggle('active', isActive);
            candidate.setAttribute('aria-selected', String(isActive));
            candidate.setAttribute('tabindex', isActive ? '0' : '-1');
        });
        panels.forEach((panel) => {
            const isActive = panel.id === panelId;
            panel.classList.toggle('active', isActive);
            panel.hidden = !isActive;
        });
        localStorage.setItem('responseViewPreference', tab.dataset.view);
        if (moveFocus) tab.focus();
    };

    const panelFor = (view) => document.getElementById(
        view === 'activity' ? 'metadata-view' : 'responses-view',
    );

    const statusFor = (view) => panelFor(view)?.querySelector(
        `[data-filter-status="${view}"]`,
    );

    const cleanUrlFromForm = (form, view) => {
        const url = new URL(window.location.href);
        const fieldNames = new Set(
            Array.from(form.elements)
                .map((field) => field.name)
                .filter(Boolean),
        );
        fieldNames.forEach((name) => url.searchParams.delete(name));
        url.searchParams.delete(view === 'activity' ? 'page' : 'response_page');

        const formData = new FormData(form);
        formData.forEach((value, name) => {
            if (value !== '') url.searchParams.append(name, value);
        });
        return url;
    };

    const updatePanel = async (view, requestedUrl) => {
        requests[view]?.abort();
        const controller = new AbortController();
        requests[view] = controller;
        const panel = panelFor(view);
        const status = statusFor(view);
        const historyUrl = new URL(requestedUrl, window.location.href);
        historyUrl.searchParams.delete('dashboard_view');
        const fetchUrl = new URL(historyUrl);
        fetchUrl.searchParams.set('dashboard_view', view);

        panel.setAttribute('aria-busy', 'true');
        if (status) status.textContent = 'Updating responses…';

        try {
            const response = await fetch(fetchUrl, {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                signal: controller.signal,
            });
            if (!response.ok) {
                throw new Error(`Response filter failed: ${response.status}`);
            }
            panel.innerHTML = await response.text();
            window.history.replaceState({}, '', historyUrl);
            const nextStatus = statusFor(view);
            if (nextStatus) nextStatus.textContent = 'Responses updated.';
        } catch (error) {
            if (error.name !== 'AbortError' && status) {
                status.textContent = 'Responses could not be updated. Please try again.';
            }
        } finally {
            if (requests[view] === controller) {
                panel.removeAttribute('aria-busy');
            }
        }
    };

    const updateFromForm = (form, view) => {
        updatePanel(view, cleanUrlFromForm(form, view));
    };

    const scheduleFormUpdate = (form, view) => {
        window.clearTimeout(debounceTimers[view]);
        debounceTimers[view] = window.setTimeout(
            () => updateFromForm(form, view),
            350,
        );
    };

    tabs.forEach((tab) => {
        tab.addEventListener('click', () => activateView(tab));
    });
    tabList.addEventListener('keydown', (event) => {
        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
        event.preventDefault();
        const currentIndex = tabs.indexOf(document.activeElement);
        let nextIndex = event.key === 'Home' ? 0 : tabs.length - 1;
        if (event.key === 'ArrowLeft') {
            nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
        }
        if (event.key === 'ArrowRight') {
            nextIndex = (currentIndex + 1) % tabs.length;
        }
        activateView(tabs[nextIndex], true);
    });

    document.addEventListener('submit', (event) => {
        const form = event.target.closest('[data-ajax-filter]');
        if (!form) return;
        event.preventDefault();
        updateFromForm(form, form.dataset.ajaxFilter);
    });

    document.addEventListener('input', (event) => {
        if (!event.target.matches('[data-auto-filter]')) return;
        const form = event.target.closest('[data-ajax-filter]');
        scheduleFormUpdate(form, form.dataset.ajaxFilter);
    });

    document.addEventListener('change', (event) => {
        const form = event.target.closest('[data-ajax-filter]');
        if (!form || event.target.matches('input[type="search"]')) return;
        window.clearTimeout(debounceTimers[form.dataset.ajaxFilter]);
        updateFromForm(form, form.dataset.ajaxFilter);
    });

    document.addEventListener('click', (event) => {
        const sortLink = event.target.closest('[data-sheet-sort]');
        if (sortLink) {
            event.preventDefault();
            updatePanel('sheet', sortLink.href);
            return;
        }

        const pageLink = event.target.closest('[data-ajax-page]');
        if (pageLink) {
            event.preventDefault();
            updatePanel(pageLink.dataset.ajaxPage, pageLink.href);
            return;
        }

        const clearButton = event.target.closest('[data-clear-filter]');
        if (!clearButton) return;
        const form = clearButton.closest('[data-ajax-filter]');
        clearButton.dataset.clearFilter.split(',').forEach((name) => {
            const field = form.elements.namedItem(name);
            if (field) field.value = '';
        });
        updateFromForm(form, form.dataset.ajaxFilter);
    });

    const savedView = localStorage.getItem('responseViewPreference') || 'metadata';
    const savedTab = tabs.find((tab) => tab.dataset.view === savedView);
    activateView(savedTab || tabs[0]);
});
