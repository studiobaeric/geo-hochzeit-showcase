// Shared round-result loading used by both end_of_game.js (moderator's
// shared screen) and results.js (each player's own screen).
import { getRoundResults } from './multiplayer.js';

// Round results (points/distance/markerLocation) are persisted server-side
// (see game_state.py's `/api/round_result`), so an end screen can be
// rebuilt from there even after a page reload or a server restart mid-game.
// The per-round photo (location/description) is static config data, so
// it's looked up from photos.json by round number rather than being
// duplicated into the persisted game state.
export async function loadResultCollection() {
    let roundResults = [];
    let photos = [];

    try {
        roundResults = await getRoundResults();
    } catch (error) {
        console.error('Could not load round results from server:', error);
    }

    try {
        const response = await fetch('/static/config/photos.json');
        if (response.ok) {
            photos = await response.json();
        }
    } catch (error) {
        console.error('Could not load photos.json:', error);
    }

    const photoById = new Map(photos.map((photo) => [photo.id, photo]));

    // photos.json ids are assigned once and never reused/renumbered (see
    // photo_config.py), so they drift out of sequence as soon as an earlier
    // picture is removed (e.g. deleting the first photo leaves ids starting
    // at 2). round_number - persisted server-side and equal to the photo's
    // id - inherits that drift, so it can't be used as the round's display
    // number. Look up each photo's current position in photos.json instead,
    // which is the same 1-based numbering players see during the game (see
    // game.js's loadPhoto/updateRoundDisplay).
    const positionById = new Map(photos.map((photo, index) => [photo.id, index + 1]));

    const resultCollection = {};
    roundResults.forEach((roundResult) => {
        resultCollection[roundResult.round_number] = {
            photo: photoById.get(roundResult.round_number) ?? null,
            players: roundResult.players,
            position: positionById.get(roundResult.round_number) ?? roundResult.round_number
        };
    });

    return resultCollection;
}

export function getSortedResults(resultCollection) {
    return Object.entries(resultCollection)
        .sort(([, first], [, second]) => first.position - second.position);
}
