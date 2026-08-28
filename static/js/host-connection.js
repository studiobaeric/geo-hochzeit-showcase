// Host-IP + join URL for the config menu's "Host-Verbindung" section, so
// guests on another device (e.g. a tablet) can join over the local WLAN
// without typing the address by hand. Fetched lazily (only once the
// spoiler-protected section is revealed) since it never changes during a
// running server process.
const HOST_INFO_ENDPOINT = '/api/host-info';

let cache = null;

export async function loadHostInfo() {
    if (cache) {
        return cache;
    }
    const response = await fetch(HOST_INFO_ENDPOINT);
    if (!response.ok) {
        throw new Error('Host-Adresse konnte nicht geladen werden.');
    }
    cache = await response.json();
    return cache;
}
