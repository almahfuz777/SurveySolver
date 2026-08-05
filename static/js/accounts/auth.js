document.querySelectorAll('[data-password-toggle]').forEach((toggle) => {
    const passwordInput = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!passwordInput) return;

    const label = toggle.querySelector('.sr-only');

    toggle.addEventListener('click', () => {
        const isVisible = passwordInput.type === 'text';
        passwordInput.type = isVisible ? 'password' : 'text';
        toggle.setAttribute('aria-pressed', String(!isVisible));
        if (label) label.textContent = isVisible ? 'Show password' : 'Hide password';
    });
});
