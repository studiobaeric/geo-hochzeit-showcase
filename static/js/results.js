/**
 * Multiplayer-Ergebnisse und Spieler-Vergleich
 */

class MultiplayerResults {
    constructor() {
        this.gameId = null;
        this.playerId = null;
        this.resultsData = null;
    }

    /**
     * Initialisiere Results-Seite
     */
    async initialize() {
        const params = new URLSearchParams(window.location.search);
        this.gameId = params.get('gameId');
        this.playerId = sessionStorage.getItem('playerId');

        if (!this.gameId) {
            // Single-Player Mode
            this.displaySinglePlayerResults();
        } else {
            // Multiplayer Mode
            await this.displayMultiplayerResults();
        }
    }

    /**
     * Zeige Single-Player Ergebnisse (Legacy)
     */
    displaySinglePlayerResults() {
        const resultsData = JSON.parse(sessionStorage.getItem('gameResults') || '{"rounds": [], "totalDistance": 0}');
        const scoreboard = document.getElementById('scoreboard');
        const totalScoreElement = document.getElementById('totalScore');

        if (resultsData.rounds && resultsData.rounds.length > 0) {
            scoreboard.innerHTML = '';

            resultsData.rounds.forEach((round, index) => {
                const row = document.createElement('div');
                row.className = 'score-row';

                const roundNum = document.createElement('div');
                roundNum.className = 'round-number';
                roundNum.textContent = round.description || 'Unbekannt';
                roundNum.onclick = () => this.showPhotoModal(index, round.description, round.filename);

                const distance = document.createElement('div');
                distance.className = 'distance';
                distance.textContent = round.distance;

                row.appendChild(roundNum);
                row.appendChild(distance);
                scoreboard.appendChild(row);
            });

            const totalDistance = resultsData.totalDistance;
            const totalText = totalDistance < 1
                ? `${Math.round(totalDistance * 1000)} Meter`
                : `${totalDistance.toFixed(2)} km`;
            totalScoreElement.textContent = totalText;
        }
    }

    /**
     * Zeige Multiplayer-Ergebnisse
     */
    async displayMultiplayerResults() {
        try {
            const response = await fetch(`/api/game/${this.gameId}/results`);
            const data = await response.json();

            if (!data.success) {
                alert('Fehler beim Laden der Ergebnisse');
                return;
            }

            this.resultsData = data.results;
            this.renderMultiplayerUI();
        } catch (error) {
            console.error('Fehler beim Laden der Ergebnisse:', error);
            alert('Fehler beim Laden der Ergebnisse');
        }
    }

    /**
     * Rendere Multiplayer-UI
     */
    renderMultiplayerUI() {
        // Update Titel
        document.querySelector('.results-container h1').textContent = '🎉 Spiel beendet!';
        document.querySelector('.results-container p').textContent = `${this.resultsData.players.length} Spieler haben gespielt`;

        // Erstelle Tabs
        const resultsContainer = document.querySelector('.results-container');
        const tabContainer = document.createElement('div');
        tabContainer.className = 'results-tabs';
        tabContainer.innerHTML = `
            <button class="tab-btn active" onclick="multiplayerResults.switchTab('ranking')">🏆 Rangliste</button>
            <button class="tab-btn" onclick="multiplayerResults.switchTab('rounds')">🗺️ Nach Runde</button>
            <button class="tab-btn" onclick="multiplayerResults.switchTab('comparison')">📊 Vergleich</button>
        `;
        resultsContainer.insertBefore(tabContainer, resultsContainer.querySelector('.score-summary'));

        // Rendering der verschiedenen Tabs
        this.renderRanking();
    }

    /**
     * Wechsele zwischen Tabs
     */
    switchTab(tab) {
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        event.target.classList.add('active');

        document.querySelectorAll('.tab-content').forEach(content => content.style.display = 'none');
        document.getElementById(`tab-${tab}`).style.display = 'block';

        if (tab === 'ranking') this.renderRanking();
        else if (tab === 'rounds') this.renderRounds();
        else if (tab === 'comparison') this.renderComparison();
    }

    /**
     * Rendere Rangliste
     */
    renderRanking() {
        const scoreboard = document.getElementById('scoreboard');
        scoreboard.innerHTML = '';

        // Sortiere Spieler nach Gesamtdistanz
        const sortedPlayers = [...this.resultsData.players].sort((a, b) => a.total_distance - b.total_distance);

        const rankingHtml = `
            <div id="tab-ranking" class="tab-content" style="display: block;">
                <div class="ranking-table">
                    ${sortedPlayers.map((player, idx) => `
                        <div class="ranking-row">
                            <div class="ranking-position">
                                <span class="medal">${this.getMedalEmoji(idx)}</span>
                                <span class="position">#${idx + 1}</span>
                            </div>
                            <div class="ranking-player">
                                <div class="player-color" style="background: ${this.getPlayerColor(player.color)}"></div>
                                <div class="player-details">
                                    <div class="player-name">${player.name}</div>
                                    <div class="player-distance">Ø ${(player.total_distance / this.resultsData.rounds.length).toFixed(2)} km/Runde</div>
                                </div>
                            </div>
                            <div class="ranking-score">${player.total_distance.toFixed(2)} km</div>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        scoreboard.innerHTML = rankingHtml;
    }

    /**
     * Rendere Pro-Runde Übersicht
     */
    renderRounds() {
        const scoreboard = document.getElementById('scoreboard');
        scoreboard.innerHTML = '';

        const roundsHtml = `
            <div id="tab-rounds" class="tab-content">
                ${this.resultsData.rounds.map((round, idx) => `
                    <div class="round-card" onclick="multiplayerResults.showRoundDetail(${idx})">
                        <div class="round-header">
                            <span class="round-title">Runde ${round.round_number}: ${round.photo.description}</span>
                            <span class="round-arrow">→</span>
                        </div>
                        <div class="round-guesses">
                            ${round.guesses
                                .sort((a, b) => a.distance_km - b.distance_km)
                                .slice(0, 3)
                                .map(guess => `
                                    <div class="guess-item">
                                        <div class="player-color" style="background: ${this.getPlayerColor(guess.player_color)}"></div>
                                        <span>${guess.player_name}</span>
                                        <span style="margin-left: auto; font-weight: bold;">${guess.distance_km.toFixed(2)} km</span>
                                    </div>
                                `).join('')}
                        </div>
                    </div>
                `).join('')}
            </div>
        `;

        scoreboard.innerHTML = roundsHtml;
    }

    /**
     * Zeige Detail einer Runde mit Karte
     */
    showRoundDetail(roundIdx) {
        const round = this.resultsData.rounds[roundIdx];
        const modal = document.createElement('div');
        modal.className = 'round-detail-modal';
        modal.innerHTML = `
            <div class="modal-content">
                <button class="modal-close" onclick="this.parentElement.parentElement.remove()">×</button>
                <h2>${round.photo.description}</h2>
                <div id="roundMap" style="height: 400px; border-radius: 10px; margin: 20px 0;"></div>
                <div class="guesses-list">
                    ${round.guesses
                        .sort((a, b) => a.distance_km - b.distance_km)
                        .map((guess, idx) => `
                            <div class="guess-item">
                                <span>${idx + 1}. ${guess.player_name}</span>
                                <span>${guess.distance_km.toFixed(2)} km</span>
                            </div>
                        `).join('')}
                </div>
                <button class="btn btn-primary" onclick="this.parentElement.parentElement.remove()">Schließen</button>
            </div>
        `;
        document.body.appendChild(modal);

        // Initialisiere Karte in Modal
        setTimeout(() => {
            const map = L.map('roundMap').setView([round.photo.location.lat, round.photo.location.lng], 8);
            L.tileLayer('/tiles/{z}/{x}/{y}.png', {
                attribution: 'Map data &copy; OpenStreetMap contributors',
                maxZoom: 18
            }).addTo(map);

            // Zeichne Marker
            round.guesses.forEach(guess => {
                L.marker([guess.latitude, guess.longitude], {
                    icon: L.icon({
                        iconUrl: `https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-${guess.player_color}.png`,
                        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                        iconSize: [25, 41],
                        iconAnchor: [12, 41]
                    })
                }).addTo(map).bindPopup(guess.player_name);
            });

            // Zeichne korrekte Position
            L.marker([round.photo.location.lat, round.photo.location.lng], {
                icon: L.icon({
                    iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
                    shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
                    iconSize: [25, 41],
                    iconAnchor: [12, 41]
                })
            }).addTo(map).bindPopup('✅ Korrekte Position');

            // Zoom auf alle Marker
            const bounds = L.latLngBounds(round.guesses.map(g => [g.latitude, g.longitude]));
            bounds.extend([round.photo.location.lat, round.photo.location.lng]);
            map.fitBounds(bounds, { padding: [50, 50] });
        }, 100);
    }

    /**
     * Rendere Vergleichstabelle
     */
    renderComparison() {
        const scoreboard = document.getElementById('scoreboard');
        const rounds = this.resultsData.rounds;

        let comparisonHtml = `
            <div id="tab-comparison" class="tab-content">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>Spieler</th>
                            ${rounds.map((_, idx) => `<th>R${idx + 1}</th>`).join('')}
                            <th>∅ km</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${this.resultsData.players
                            .sort((a, b) => a.total_distance - b.total_distance)
                            .map(player => {
                                let playerHtml = `<tr>
                                    <td class="player-cell">
                                        <div class="player-color" style="background: ${this.getPlayerColor(player.color)}"></div>
                                        ${player.name}
                                    </td>`;

                                rounds.forEach(round => {
                                    const guess = round.guesses.find(g => g.player_id === player.id);
                                    const distance = guess ? guess.distance_km.toFixed(1) : '-';
                                    playerHtml += `<td>${distance}${guess ? ' km' : ''}</td>`;
                                });

                                const avg = (player.total_distance / rounds.length).toFixed(2);
                                playerHtml += `<td><strong>${avg} km</strong></td></tr>`;
                                return playerHtml;
                            }).join('')}
                    </tbody>
                </table>
            </div>
        `;

        scoreboard.innerHTML = comparisonHtml;
    }

    /**
     * Hilfsfunktionen
     */
    getMedalEmoji(position) {
        const medals = ['🥇', '🥈', '🥉'];
        return medals[position] || '🎖️';
    }

    getPlayerColor(colorName) {
        const colors = {
            'blue': '#4169E1',
            'green': '#28A745',
            'purple': '#9B59B6',
            'orange': '#FF8C00',
            'yellow': '#FFD700',
            'pink': '#FF69B4'
        };
        return colors[colorName] || '#667eea';
    }

    showPhotoModal(index, description, filename) {
        const modal = document.getElementById('photoModal');
        const modalImage = document.getElementById('modalImage');
        const modalTitle = document.getElementById('modalTitle');

        modalTitle.textContent = description || 'Foto';
        modalImage.src = `/static/photos/${filename}`;
        modal.classList.add('active');
    }
}

// Erstelle globale Instanz
const multiplayerResults = new MultiplayerResults();
window.addEventListener('load', () => multiplayerResults.initialize());

