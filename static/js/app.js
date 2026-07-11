const navToggle = document.querySelector('.nav-toggle');
const primaryNavigation = document.querySelector('.primary-nav');

if (navToggle && primaryNavigation) {
    navToggle.addEventListener('click', () => {
        const isOpen = navToggle.getAttribute('aria-expanded') === 'true';
        navToggle.setAttribute('aria-expanded', String(!isOpen));
        primaryNavigation.classList.toggle('is-open', !isOpen);
    });

    primaryNavigation.addEventListener('click', (event) => {
        if (event.target.closest('a')) {
            navToggle.setAttribute('aria-expanded', 'false');
            primaryNavigation.classList.remove('is-open');
        }
    });
}

document.querySelectorAll('[data-copy-previous]').forEach((button) => {
    button.addEventListener('click', async () => {
        const input = button.previousElementSibling;
        if (!input) return;
        try {
            await navigator.clipboard.writeText(input.value);
        } catch {
            input.select();
            document.execCommand('copy');
        }
        button.textContent = 'Copied';
    });
});
