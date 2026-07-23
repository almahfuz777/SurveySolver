(function () {
    'use strict';

    /* --- Avatar upload + live preview ---------------------------------- */
    (function avatarUploader() {
        const input = document.querySelector('[data-avatar-input]');
        const img = document.querySelector('[data-avatar-img]');
        const initials = document.querySelector('[data-avatar-initials]');
        const removeBtn = document.querySelector('[data-avatar-remove]');
        const clear = document.querySelector('input[name$="-clear"]');
        if (!input || !img) return;

        const showImage = (src) => {
            img.src = src;
            img.hidden = false;
            if (initials) initials.hidden = true;
            if (removeBtn) removeBtn.hidden = false;
        };
        const showInitials = () => {
            img.hidden = true;
            img.removeAttribute('src');
            if (initials) initials.hidden = false;
            if (removeBtn) removeBtn.hidden = true;
        };

        input.addEventListener('change', () => {
            const file = input.files && input.files[0];
            if (!file) return;
            if (clear) clear.checked = false;
            const reader = new FileReader();
            reader.onload = (event) => showImage(event.target.result);
            reader.readAsDataURL(file);
        });

        if (removeBtn) {
            removeBtn.addEventListener('click', () => {
                input.value = '';
                if (clear) clear.checked = true;
                showInitials();
            });
        }
    })();

    /* --- Region depends on the chosen country -------------------------- */
    (function regionDependency() {
        const country = document.querySelector('[data-region-country]');
        const region = document.querySelector('[data-region-select]');
        if (!country || !region) return;
        const options = Array.from(region.options);

        const sync = () => {
            const code = country.value;
            let stillValid = false;
            options.forEach((option) => {
                const match = option.value === '' || (code && option.value.startsWith(code + '-'));
                option.hidden = !match;
                option.disabled = !match && option.value !== '';
                if (match && option.value === region.value) stillValid = true;
            });
            if (!stillValid) region.value = '';
            region.disabled = !code;
            const placeholder = options[0];
            if (placeholder && placeholder.value === '') {
                placeholder.textContent = code ? 'Select your region' : 'Select your country first';
            }
        };

        country.addEventListener('change', sync);
        sync();
    })();

    /* --- Show self-describe only for that gender ----------------------- */
    (function genderSelfDescribe() {
        const select = document.querySelector('[data-gender-select]');
        const field = document.querySelector('[data-selfdescribe-field]');
        if (!select || !field) return;
        const sync = () => { field.hidden = select.value !== 'self_describe'; };
        select.addEventListener('change', sync);
        sync();
    })();

    /* --- Searchable multi-select chips (languages) --------------------- */
    document.querySelectorAll('[data-country-select]').forEach((wrapper) => {
        const search = wrapper.querySelector('[data-country-search]');
        const dropdown = wrapper.querySelector('[data-country-dropdown]');
        const tags = wrapper.querySelector('[data-country-tags]');
        const count = wrapper.querySelector('[data-country-count]');
        const clear = wrapper.querySelector('[data-country-clear]');
        const empty = wrapper.querySelector('[data-country-empty]');
        const boxes = Array.from(dropdown.querySelectorAll('input[type="checkbox"]'));
        const noun = wrapper.dataset.noun || 'items';

        const close = () => {
            wrapper.classList.remove('is-open');
            dropdown.hidden = true;
            search.setAttribute('aria-expanded', 'false');
        };
        const open = () => {
            wrapper.classList.add('is-open');
            dropdown.hidden = false;
            search.setAttribute('aria-expanded', 'true');
        };

        const renderTags = () => {
            tags.innerHTML = '';
            const selected = boxes.filter((box) => box.checked);
            selected.forEach((box) => {
                const label = box.closest('label');
                const name = label ? label.textContent.trim() : box.value;
                const tag = document.createElement('span');
                tag.className = 'country-tag';
                const text = document.createElement('span');
                const remove = document.createElement('button');
                text.textContent = name;
                remove.type = 'button';
                remove.setAttribute('aria-label', 'Remove ' + name);
                remove.textContent = '✕';
                remove.addEventListener('click', () => {
                    box.checked = false;
                    renderTags();
                });
                tag.append(text, remove);
                tags.appendChild(tag);
            });
            count.textContent = selected.length ? selected.length + ' selected' : 'No ' + noun + ' selected';
            clear.hidden = selected.length === 0;
        };

        const filter = () => {
            const query = search.value.trim().toLowerCase();
            let matches = 0;
            boxes.forEach((box) => {
                const label = box.closest('label');
                const match = !query || label.textContent.trim().toLowerCase().includes(query);
                label.hidden = !match;
                if (match) matches += 1;
            });
            if (empty) empty.hidden = matches !== 0;
        };

        search.addEventListener('focus', open);
        search.addEventListener('input', filter);
        search.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') { close(); search.blur(); }
        });
        dropdown.addEventListener('change', renderTags);
        clear.addEventListener('click', () => {
            boxes.forEach((box) => { box.checked = false; });
            renderTags();
            search.focus();
        });
        document.addEventListener('click', (event) => {
            if (!wrapper.contains(event.target)) close();
        });

        renderTags();
        filter();
    });
})();
