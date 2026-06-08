const currentPhotoImage = document.getElementById('currentPhotoImage');
const currentPhotoFallback = document.getElementById('currentPhotoFallback');
const mapStartCenter = [49.3690, 9.5436];
const mapStartZoom = 5;

let leftPlayerMap = null;
let rightPlayerMap = null;
let leftPlayerMarker = null;
let rightPlayerMarker = null;
let isPmtilesProtocolRegistered = false;

async function loadCurrentPhoto(photo=0) {
    try {
        const response = await fetch('/static/data/photos.json');
        const photos = await response.json();
        const currentPhoto = photos[photo];

        if (!currentPhoto) return;

        currentPhotoImage.src = `/static/photos/${currentPhoto.filename}`;
        currentPhotoImage.classList.add('is-loaded');
        currentPhotoFallback.classList.add('is-hidden');
    } catch (error) {
        console.error('Moderator photo could not be loaded:', error);
    }
}

async function updateMapPosition(record){

}






function createMap(containerId) {
    return L.map(containerId, {
        minZoom: 1,
        maxZoom: 18,
        zoomControl: true
    }).setView(mapStartCenter, mapStartZoom);
}

function normalizeBasemapStyle(style) {
    const origin = window.location.origin;
    const normalizedStyle = JSON.parse(JSON.stringify(style));

    normalizedStyle.sprite = origin + normalizedStyle.sprite;
    normalizedStyle.glyphs = origin + normalizedStyle.glyphs;
    normalizedStyle.sources.protomaps.url = `pmtiles://${origin}/static/data/basemap.pmtiles`;

    return normalizedStyle;
}

async function addBasemap(map) {
    const response = await fetch('/static/data/basemap-style.json');
    const style = normalizeBasemapStyle(await response.json());

    L.maplibreGL({
        style,
        attribution: 'Map data &copy; OpenStreetMap contributors'
    }).addTo(map);
}

async function initModeratorMaps() {
    if (!isPmtilesProtocolRegistered) {
        const pmtilesProtocol = new pmtiles.Protocol();
        maplibregl.addProtocol('pmtiles', pmtilesProtocol.tile);
        isPmtilesProtocolRegistered = true;
    }

    leftPlayerMap = createMap('leftPlayerMap');
    rightPlayerMap = createMap('rightPlayerMap');

    await Promise.all([
        addBasemap(leftPlayerMap),
        addBasemap(rightPlayerMap)
    ]);

    setTimeout(() => {
        leftPlayerMap.invalidateSize(true);
        rightPlayerMap.invalidateSize(true);
    }, 200);
}

loadCurrentPhoto();
initModeratorMaps().catch((error) => {
    console.error('Moderator maps could not be loaded:', error);
});

window.addEventListener('resize', () => {
    leftPlayerMap?.invalidateSize(true);
    rightPlayerMap?.invalidateSize(true);
});
