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

// Color stops for getRadiusBands()' falloff visualization (#144 follow-up):
// orange matches the full-points circle drawn around perfect_radius_meters
// (see moderator.js/end_of_game.js), fading to blue as points decay toward
// min_points, so "hot" (orange) vs. "cold" (blue) reads the same way as the
// existing full-points circle rather than introducing an unrelated palette.
const HOT_COLOR = [249, 115, 22]; // #f97316
const COLD_COLOR = [59, 130, 246]; // #3b82f6

function bandColor(fraction) {
    const clamped = Math.max(0, Math.min(1, fraction));
    const channel = (hot, cold) => Math.round(cold + (hot - cold) * clamped);
    return `rgb(${channel(HOT_COLOR[0], COLD_COLOR[0])}, ${channel(HOT_COLOR[1], COLD_COLOR[1])}, ${channel(HOT_COLOR[2], COLD_COLOR[2])})`;
}

const RADIUS_BAND_COUNT = 6;

/**
 * Concentric bands visualizing how points decay beyond the full-points
 * radius, for drawing as a "heatmap" of circles around the target location
 * (#144 follow-up) - makes the exponential/linear algorithms' falloff
 * shape visible, not just the full-points cutoff itself.
 *
 * Returns bands outermost-first as { radius, color }: the caller draws a
 * filled circle for each, largest radius first, so smaller (hotter) bands
 * layer on top and only the ring between consecutive radii shows each
 * band's own color once done.
 *
 * Empty for "step" - a hard cutoff has no falloff shape to visualize
 * (that's exactly what the plain full-points circle already shows) - and
 * for a misconfigured falloff (outer radius at or inside the full-points
 * radius).
 */
export function getRadiusBands(config = cache) {
    if (config.algorithm === 'step') {
        return [];
    }

    const perfectRadius = config.perfect_radius_meters;
    const outerRadius = config.algorithm === 'linear'
        ? config.max_distance_meters
        // Exponential decay never actually reaches min_points, so there's
        // no natural outer edge like linear's max_distance_meters - one
        // distance_scale_meters out, points have decayed ~63% of the way
        // from max to min, which is enough of the curve's shape to be
        // worth drawing without the bands sprawling arbitrarily far.
        : perfectRadius + config.distance_scale_meters;

    if (!(outerRadius > perfectRadius)) {
        return [];
    }

    const bands = [];
    for (let i = RADIUS_BAND_COUNT; i >= 1; i--) {
        const radius = perfectRadius + ((outerRadius - perfectRadius) * i) / RADIUS_BAND_COUNT;
        const points = calculateRoundPoints(radius, config);
        const fraction = (points - config.min_points) / ((config.max_points - config.min_points) || 1);
        bands.push({ radius, color: bandColor(fraction) });
    }
    return bands;
}
