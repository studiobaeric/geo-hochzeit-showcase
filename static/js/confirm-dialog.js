// Reusable "are you sure?" dialog for destructive actions - see #45, where an
// accidental click on the moderator's reset button discarded the running
// game with no way to undo it. Builds one overlay lazily and reuses it, the
// same lazy-singleton pattern as position-picker.js.
import { t } from './i18n.js';

let dom = null;
let resolveFn = null;

function buildDom() {
    if (dom) return dom;

    const overlay = document.createElement('div');
    overlay.className = 'confirm-dialog-overlay';
    overlay.innerHTML = `
        <div class="confirm-dialog" role="alertdialog" aria-modal="true">
            <p class="confirm-dialog-message"></p>
            <div class="confirm-dialog-actions">
                <button type="button" class="confirm-dialog-cancel"></button>
                <button type="button" class="confirm-dialog-confirm"></button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    dom = {
        overlay,
        message: overlay.querySelector('.confirm-dialog-message'),
        cancelButton: overlay.querySelector('.confirm-dialog-cancel'),
        confirmButton: overlay.querySelector('.confirm-dialog-confirm')
    };

    dom.cancelButton.addEventListener('click', () => finish(false));
    dom.confirmButton.addEventListener('click', () => finish(true));
    overlay.addEventListener('click', (event) => {
        if (event.target === overlay) finish(false);
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && overlay.classList.contains('is-active')) finish(false);
    });

    return dom;
}

function finish(result) {
    dom.overlay.classList.remove('is-active');
    const resolve = resolveFn;
    resolveFn = null;
    resolve?.(result);
}

// Resolves true if the user confirms, false if they cancel or dismiss it.
export function confirmDialog(message, { confirmLabel = t('common.confirm'), cancelLabel = t('common.cancel') } = {}) {
    const d = buildDom();
    d.message.textContent = message;
    d.confirmButton.textContent = confirmLabel;
    d.cancelButton.textContent = cancelLabel;
    d.overlay.classList.add('is-active');

    return new Promise((resolve) => {
        resolveFn = resolve;
    });
}
