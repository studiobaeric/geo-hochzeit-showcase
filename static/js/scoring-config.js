// Runtime-editable point-scoring settings (set via the /config menu),
// backed by /api/scoring-config so a change made on one device applies to
// every device - see #127. calculateRoundPoints() is the actual algorithm
// implementation; it lives here (not in moderator.js) so the scoring math
// and the config it reads travel together.
const CONFIG_ENDPOINT = '/api/scoring-config';

const DEFAULTS = {
    algorithm: 'exponential',
    max_points: 1000,
    min_points: 100,
    perfect_radius_meters: 500,
    distance_scale_meters: 100000,
    max_distance_meters: 20000
};

let cache = { ...DEFAULTS };

export function getScoringConfig() {
    return cache;
}

export async function loadScoringConfig() {
    try {
        const response = await fetch(CONFIG_ENDPOINT);
        if (response.ok) {
            cache = await response.json();
        }
    } catch (error) {
        console.error('Konnte Punkte-Konfiguration nicht laden, verwende Standardwerte:', error);
    }
    return cache;
}

export async function saveScoringConfig(updates) {
    const response = await fetch(CONFIG_ENDPOINT, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
    });

    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Speichern fehlgeschlagen (${response.status})`);
    }

    cache = await response.json();
    return cache;
}

// Applies a scoring_config record received from the shared /api/events
// stream (see multiplayer.js) - same pattern as theme.js's
// onThemeConfigEvent, just without an immediate visual effect to apply.
export function onScoringConfigEvent(record) {
    cache = record;
}

/**
 * Turns a guess's distance from the target into a point total, per the
 * configured algorithm (config.algorithm, default "exponential" if config
 * is omitted or the value is unrecognized):
 *
 * - "exponential": full points inside perfect_radius_meters, then decays
 *   exponentially towards min_points over distance_scale_meters - a very
 *   far guess still scores something. This is the original/default
 *   algorithm.
 * - "linear": full points inside perfect_radius_meters, then falls off in
 *   a straight line down to min_points at max_distance_meters (and stays
 *   at min_points beyond that).
 * - "step": full points inside perfect_radius_meters, min_points
 *   immediately beyond it - the literal "close enough or not" cutoff
 *   requested in #127.
 *
 * distanceMeters may be null/undefined (the player never placed a guess
 * this round), in which case the result is always 0.
 */
export function calculateRoundPoints(distanceMeters, config = cache) {
    if (distanceMeters === null || distanceMeters === undefined || !Number.isFinite(distanceMeters)) {
        return 0;
    }

    const maxPoints = config.max_points;
    const minPoints = config.min_points;
    const perfectRadius = config.perfect_radius_meters;

    if (distanceMeters <= perfectRadius) {
        return maxPoints;
    }

    const effectiveDistance = distanceMeters - perfectRadius;
    let points;

    if (config.algorithm === 'linear') {
        const falloffDistance = Math.max(1, config.max_distance_meters - perfectRadius);
        const fraction = Math.max(0, 1 - effectiveDistance / falloffDistance);
        points = minPoints + (maxPoints - minPoints) * fraction;
    } else if (config.algorithm === 'step') {
        points = minPoints;
    } else {
        // "exponential" - also the fallback for an unrecognized value.
        points = minPoints + (maxPoints - minPoints) * Math.exp(-effectiveDistance / config.distance_scale_meters);
    }

    points = Math.round(points);
    return Math.max(minPoints, Math.min(maxPoints, points));
}
