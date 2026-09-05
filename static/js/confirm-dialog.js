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
            <input type="text" class="confirm-dialog-phrase-input" autocomplete="off" autocapitalize="off" spellcheck="false" hidden>
            <div class="confirm-dialog-actions">
                <button type="button" class="confirm-dialog-cancel"></button>
                <button type="button" class="confirm-dialog-confirm"></button>
            </div>
        </div>`;
    document.body.appendChild(overlay);

    dom = {
        overlay,
        message: overlay.querySelector('.confirm-dialog-message'),
        phraseInput: overlay.querySelector('.confirm-dialog-phrase-input'),
        cancelButton: overlay.querySelector('.confirm-dialog-cancel'),
        confirmButton: overlay.querySelector('.confirm-dialog-confirm')
    };

    dom.cancelButton.addEventListener('click', () => finish(false));
    dom.confirmButton.addEventListener('click', () => {
        if (!dom.confirmButton.disabled) finish(true);
    });
    dom.phraseInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !dom.confirmButton.disabled) finish(true);
    });
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
    dom.phraseInput.oninput = null;
    const resolve = resolveFn;
    resolveFn = null;
    resolve?.(result);
}

// Resolves true if the user confirms, false if they cancel or dismiss it.
//
// Pass `requirePhrase` for the most destructive actions, where a single
// click/Enter must not be enough (e.g. the config page's full game reset,
// #137) - this reveals a text input and keeps the confirm button disabled
// until the user has typed that exact phrase into it.
export function confirmDialog(
    message,
    { confirmLabel = t('common.confirm'), cancelLabel = t('common.cancel'), requirePhrase } = {}
) {
    const d = buildDom();
    d.message.textContent = message;
    d.confirmButton.textContent = confirmLabel;
    d.cancelButton.textContent = cancelLabel;

    d.phraseInput.hidden = !requirePhrase;
    d.phraseInput.value = '';
    if (requirePhrase) {
        d.phraseInput.placeholder = requirePhrase;
        d.confirmButton.disabled = true;
        d.phraseInput.oninput = () => {
            d.confirmButton.disabled = d.phraseInput.value !== requirePhrase;
        };
    } else {
        d.confirmButton.disabled = false;
        d.phraseInput.oninput = null;
    }

    d.overlay.classList.add('is-active');
    if (requirePhrase) d.phraseInput.focus();

    return new Promise((resolve) => {
        resolveFn = resolve;
    });
}
