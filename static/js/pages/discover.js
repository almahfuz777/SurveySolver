const filterForm = document.querySelector('[data-live-filters]');
const discoveryResults = document.querySelector('[data-discovery-results]');
const filterStatus = document.querySelector('[data-filter-status]');

if (filterForm && discoveryResults && filterStatus) {
    let activeRequest;

    const updateResults = async () => {
        activeRequest?.abort();
        const requestController = new AbortController();
        activeRequest = requestController;

        const query = new URLSearchParams(new FormData(filterForm));
        for (const [key, value] of [...query.entries()]) {
            if (!value) query.delete(key);
        }

        const requestUrl = new URL(filterForm.action, window.location.origin);
        requestUrl.search = query.toString();
        discoveryResults.setAttribute('aria-busy', 'true');
        filterStatus.textContent = 'Updating studies…';

        try {
            const response = await fetch(requestUrl, {
                headers: {'X-Requested-With': 'XMLHttpRequest'},
                signal: requestController.signal,
            });
            if (!response.ok) throw new Error(`Filter request failed: ${response.status}`);

            discoveryResults.innerHTML = await response.text();
            window.history.replaceState({}, '', requestUrl);
            filterStatus.textContent = 'Studies updated.';
        } catch (error) {
            if (error.name !== 'AbortError') {
                filterStatus.textContent = 'Studies could not be updated. Please try again.';
            }
        } finally {
            if (activeRequest === requestController) {
                discoveryResults.removeAttribute('aria-busy');
            }
        }
    };

    filterForm.addEventListener('change', updateResults);
    filterForm.addEventListener('submit', (event) => {
        event.preventDefault();
        updateResults();
    });
}
