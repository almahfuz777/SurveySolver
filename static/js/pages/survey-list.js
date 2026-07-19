(() => {
  const storageKey = 'surveysolver:survey-list-view';
  const allowedViews = new Set(['card', 'compact']);

  document.addEventListener('DOMContentLoaded', () => {
    const grid = document.querySelector('[data-survey-grid]');
    const select = document.querySelector('[data-survey-view]');
    if (!grid || !select) return;

    const applyView = (view) => {
      const resolvedView = allowedViews.has(view) ? view : 'card';
      grid.dataset.view = resolvedView;
      select.value = resolvedView;
    };

    let savedView;
    try {
      savedView = window.localStorage.getItem(storageKey);
    } catch {
      savedView = null;
    }
    applyView(savedView);

    select.addEventListener('change', () => {
      applyView(select.value);
      try {
        window.localStorage.setItem(storageKey, select.value);
      } catch {
        // The selected layout still applies when storage is unavailable.
      }
    });
  });
})();
