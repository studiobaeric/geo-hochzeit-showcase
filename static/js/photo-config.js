// Round-photo management (upload, position, description), backed by
// /api/round-photos. static/config/photos.json (the file this API reads
// and writes) is the single source of truth for round photos - the same
// file static/js/game.js, static/js/moderator.js and
// static/js/end_of_game.js load directly to run the actual game.
const LIST_ENDPOINT = '/api/round-photos';
const EXIF_ENDPOINT = '/api/round-photos/exif-location';

export async function loadRoundPhotos() {
    const response = await fetch(LIST_ENDPOINT);
    if (!response.ok) {
        throw new Error(`Laden fehlgeschlagen (${response.status})`);
    }
    return response.json();
}

export async function fetchExifLocation(file) {
    const formData = new FormData();
    formData.append('photo', file);

    const response = await fetch(EXIF_ENDPOINT, { method: 'POST', body: formData });
    if (!response.ok) {
        return { lat: null, lng: null };
    }
    return response.json();
}

export async function uploadRoundPhoto({ file, description, lat, lng }) {
    const formData = new FormData();
    formData.append('photo', file);
    formData.append('description', description);
    formData.append('lat', String(lat));
    formData.append('lng', String(lng));

    const response = await fetch(LIST_ENDPOINT, { method: 'POST', body: formData });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || `Hochladen fehlgeschlagen (${response.status})`);
    }
    return data;
}

export async function updateRoundPhoto(id, { description, lat, lng }) {
    const response = await fetch(`${LIST_ENDPOINT}/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ description, location: { lat, lng } })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(data.error || `Speichern fehlgeschlagen (${response.status})`);
    }
    return data;
}

export async function deleteRoundPhoto(id) {
    const response = await fetch(`${LIST_ENDPOINT}/${id}`, { method: 'DELETE' });
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Löschen fehlgeschlagen (${response.status})`);
    }
}
