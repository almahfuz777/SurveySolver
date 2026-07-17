document.querySelectorAll('[data-password-toggle]').forEach((toggle) => {
    const passwordInput = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!passwordInput) return;

    toggle.addEventListener('click', () => {
        const isVisible = passwordInput.type === 'text';
        passwordInput.type = isVisible ? 'password' : 'text';
        toggle.textContent = isVisible ? 'Show' : 'Hide';
        toggle.setAttribute('aria-pressed', String(!isVisible));
    });
});
