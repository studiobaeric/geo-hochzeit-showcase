// Full "factory reset" back to the shipped defaults - the config page's
// danger-zone button (#137), wired to game_state.py's own
// POST /api/reset-to-defaults (the same endpoint tools/reset_state.py calls
// against an already-running server, see #72).
import { tf } from './i18n.js';

const RESET_ENDPOINT = '/api/reset-to-defaults';

export async function resetGameToDefaults() {
    const response = await fetch(RESET_ENDPOINT, { method: 'POST' });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || tf('api.save_failed', { status: response.status }));
    }
    return response.json();
}
