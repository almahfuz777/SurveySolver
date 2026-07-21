// Site-wide in-page confirmation for `form[data-confirm]`, replacing the native
// browser confirm() dialog. The builder ships its own modal, so this stays out
// of its way to avoid double dialogs.
(() => {
  if (document.querySelector('[data-builder]')) return;

  const forms = document.querySelectorAll('form[data-confirm]');
  if (!forms.length) return;

  const style = document.createElement('style');
  style.textContent = `
    .site-confirm-overlay { position: fixed; inset: 0; z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 1rem; background: rgba(23, 22, 43, 0.45); opacity: 0; visibility: hidden; transition: opacity 140ms ease; }
    .site-confirm-overlay.is-open { opacity: 1; visibility: visible; }
    .site-confirm { width: min(24rem, 100%); padding: 1.25rem 1.25rem 1rem; background: var(--surface-raised, #fff); border-radius: var(--radius-md, 0.75rem); box-shadow: 0 12px 32px rgba(23, 22, 43, 0.24); transform: scale(0.96); transition: transform 140ms ease; }
    .site-confirm-overlay.is-open .site-confirm { transform: scale(1); }
    .site-confirm-text { margin: 0 0 1.1rem; color: var(--ink-950, #17162b); font-size: 0.95rem; font-weight: 600; line-height: 1.45; }
    .site-confirm-actions { display: flex; justify-content: flex-end; gap: 0.5rem; }
  `;
  document.head.append(style);

  const overlay = document.createElement('div');
  overlay.className = 'site-confirm-overlay';
  overlay.innerHTML =
    '<div class="site-confirm" role="alertdialog" aria-modal="true" aria-labelledby="site-confirm-text">' +
      '<p class="site-confirm-text" id="site-confirm-text"></p>' +
      '<div class="site-confirm-actions">' +
        '<button type="button" class="button button-secondary button-small" data-cancel>Cancel</button>' +
        '<button type="button" class="button button-danger button-small" data-ok>Confirm</button>' +
      '</div>' +
    '</div>';
  document.body.append(overlay);

  const textEl = overlay.querySelector('.site-confirm-text');
  const okBtn = overlay.querySelector('[data-ok]');
  const cancelBtn = overlay.querySelector('[data-cancel]');
  let resolver = null;
  let lastFocus = null;

  const close = (result) => {
    overlay.classList.remove('is-open');
    if (lastFocus) lastFocus.focus();
    if (resolver) { const r = resolver; resolver = null; r(result); }
  };
  const ask = (message, okLabel) => {
    textEl.textContent = message;
    okBtn.textContent = okLabel || 'Confirm';
    lastFocus = document.activeElement;
    overlay.classList.add('is-open');
    cancelBtn.focus();
    return new Promise((resolve) => { resolver = resolve; });
  };

  okBtn.addEventListener('click', () => close(true));
  cancelBtn.addEventListener('click', () => close(false));
  overlay.addEventListener('click', (event) => { if (event.target === overlay) close(false); });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && overlay.classList.contains('is-open')) close(false);
  });

  forms.forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (form.dataset.confirmBypass === 'true') { delete form.dataset.confirmBypass; return; }
      event.preventDefault();
      ask(form.dataset.confirm, form.dataset.confirmOk).then((ok) => {
        if (!ok) return;
        form.dataset.confirmBypass = 'true';
        if (form.requestSubmit) form.requestSubmit(); else form.submit();
      });
    });
  });
})();
