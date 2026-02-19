// Initialisiere die Karte (Beispiel: Deutschland Zentrum)
const map = L.map('map').setView([51.1657, 10.4515], 6);

// Verwende lokale Tiles statt Online-Quelle
L.tileLayer('/tiles/{z}/{x}/{y}.png', {
    attribution: 'Map data &copy; OpenStreetMap contributors',
    maxZoom: 18,
    minZoom: 3
}).addTo(map);

// Beispiel-Marker (kannst du später für das Spiel verwenden)
const marker = L.marker([51.1657, 10.4515]).addTo(map);
marker.bindPopup('<b>Beispiel-Location</b><br>Hier könnte ein Hochzeits-Foto sein!');
