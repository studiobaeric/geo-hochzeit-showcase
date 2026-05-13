from flask import Flask, render_template, send_from_directory, request, jsonify, redirect
from flask_socketio import SocketIO, emit, join_room
from flask_cors import CORS
import os
import secrets
from db import db
from game_manager import GameManager

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///geoguesser.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialisiere Datenbank
db.init_app(app)

# Initialisiere SocketIO für Live-Updates
socketio = SocketIO(app, cors_allowed_origins="*")

# CORS aktivieren
CORS(app)

# Erstelle DB-Tabellen
with app.app_context():
    db.create_all()


# ============== Routes ==============

@app.route('/')
def start():
    return render_template('start.html')


@app.route('/lobby')
def lobby():
    return render_template('lobby.html')


@app.route('/play')
def play():
    return render_template('game.html')


@app.route('/results')
def results():
    return render_template('results.html')


@app.route('/moderator')
def moderator():
    gameId = request.args.get('gameId')
    if not gameId:
        return redirect('/')
    return render_template('moderator_game.html')


@app.route('/tiles/<int:z>/<int:x>/<int:y>.png')
def tiles(z, x, y):
    """Serve offline map tiles"""
    tile_dir = os.path.join('static', 'tiles', str(z), str(x))
    return send_from_directory(tile_dir, f'{y}.png')


# ============== API ==============

@app.route('/api/game/create', methods=['POST'])
def create_game():
    try:
        game = GameManager.create_game()
        return jsonify({
            'success': True,
            'game_id': game.id,
            'moderator_token': game.moderator_token
        }), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/join', methods=['POST'])
def join_game(game_id):
    """Spieler tritt Spiel bei"""
    try:
        data = request.json
        player_name = data.get('player_name', 'Spieler')

        game = GameManager.get_game(game_id)
        if not game:
            return jsonify({'success': False, 'error': 'Spiel nicht gefunden'}), 404

        if game.status != 'waiting':
            return jsonify({'success': False, 'error': 'Spiel hat bereits gestartet'}), 400

        player = GameManager.add_player(game_id, player_name)

        # Broadcast an andere Spieler
        socketio.emit('player_joined', {
            'player_id': player.id,
            'player_name': player.name,
            'player_count': len(game.players)
        }, room=game_id)

        return jsonify({
            'success': True,
            'player_id': player.id,
            'player_name': player.name,
            'color': player.color
        }), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/start', methods=['POST'])
def start_game(game_id):
    """Starte Spiel"""
    try:
        success = GameManager.start_game(game_id)
        if not success:
            return jsonify({'success': False, 'error': 'Spiel konnte nicht gestartet werden'}), 400

        game = GameManager.get_game(game_id)
        state = GameManager.get_game_state(game_id)

        # Broadcast an alle Spieler
        socketio.emit('game_started', state, room=game_id)

        return jsonify({'success': True, 'game_state': state}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/state', methods=['GET'])
def get_game_state(game_id):
    """Hole aktuellen Spielzustand"""
    try:
        state = GameManager.get_game_state(game_id)
        if not state:
            return jsonify({'success': False, 'error': 'Spiel nicht gefunden'}), 404

        return jsonify({'success': True, 'state': state}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/guess', methods=['POST'])
def submit_guess(game_id):
    """Speichere Tipp eines Spielers"""
    try:
        data = request.json
        player_id = data.get('player_id')
        round_number = data.get('round_number')
        latitude = data.get('latitude')
        longitude = data.get('longitude')

        guess = GameManager.submit_guess(game_id, player_id, round_number, latitude, longitude)
        if not guess:
            return jsonify({'success': False, 'error': 'Tipp konnte nicht gespeichert werden'}), 400

        # Broadcast Tipp an andere Spieler (für Moderatormodus)
        socketio.emit('player_guess', {
            'player_id': player_id,
            'round_number': round_number,
            'latitude': latitude,
            'longitude': longitude,
            'distance_km': guess.distance_km
        }, room=game_id)

        # Prüfe ob alle Spieler fertig sind
        round_status = GameManager.get_round_status(game_id)
        if round_status and round_status['all_ready']:
            print(f"✅ ALLE SPIELER FERTIG! Round {round_status['round_number']}")
            socketio.emit('all_players_ready', {
                'round_id': round_status['round_id'],
                'round_number': round_status['round_number'],
                'total_players': round_status['total_players']
            }, room=game_id, skip_sid=request.sid)

        return jsonify({
            'success': True,
            'guess_id': guess.id,
            'distance_km': guess.distance_km,
            'message': 'Tipp erfolgreich gespeichert'
        }), 201
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/results', methods=['GET'])
def get_game_results(game_id):
    """Hole Ergebnisse des Spiels"""
    try:
        results = GameManager.get_game_results(game_id)
        if not results:
            return jsonify({'success': False, 'error': 'Spiel nicht gefunden'}), 404

        return jsonify({'success': True, 'results': results}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/end', methods=['POST'])
def end_game(game_id):
    """Beende Spiel"""
    try:
        success = GameManager.end_game(game_id)
        if not success:
            return jsonify({'success': False, 'error': 'Spiel konnte nicht beendet werden'}), 400

        results = GameManager.get_game_results(game_id)

        # Broadcast an alle Spieler
        socketio.emit('game_ended', results, room=game_id)

        return jsonify({'success': True, 'results': results}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/round/<round_id>', methods=['GET'])
def get_round_data(game_id, round_id):
    """Hole Details einer spezifischen Runde"""
    try:
        round_obj = Round.query.get(round_id)
        if not round_obj or round_obj.game_id != game_id:
            return jsonify({'success': False, 'error': 'Runde nicht gefunden'}), 404

        photos = GameManager.get_photos()
        photo = next((p for p in photos if p['id'] == round_obj.photo_id), None)

        round_data = {
            'round_id': round_obj.id,
            'round_number': round_obj.round_number,
            'photo': photo,
            'actual_location': photo['location'] if photo else None,
            'guesses': [g.to_dict() for g in round_obj.guesses]
        }

        # Enriche Guesses mit Player-Infos
        for i, guess in enumerate(round_data['guesses']):
            player = Player.query.get(guess['player_id'])
            if player:
                guess['player_name'] = player.name
                guess['player_color'] = player.color

        return jsonify({'success': True, 'round_data': round_data}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/lobby', methods=['GET'])
def get_game_lobby(game_id):
    """Hole Lobby-Informationen"""
    try:
        game = GameManager.get_game(game_id)
        if not game:
            return jsonify({'success': False, 'error': 'Spiel nicht gefunden'}), 404

        return jsonify({
            'success': True,
            'game_id': game.id,
            'status': game.status,
            'player_count': len(game.players),
            'players': [p.to_dict() for p in game.players]
        }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/round/status', methods=['GET'])
def get_round_status(game_id):
    """Hole Status der aktuellen Runde"""
    try:
        status = GameManager.get_round_status(game_id)
        if not status:
            return jsonify({'success': False, 'error': 'Keine aktive Runde'}), 404
        
        return jsonify({'success': True, 'status': status}), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/game/<game_id>/round/next', methods=['POST'])
def progress_round(game_id):
    """Gehe zur nächsten Runde"""
    try:
        has_next = GameManager.progress_to_next_round(game_id)
        
        if has_next:
            # Es gibt eine nächste Runde
            current_round = GameManager.get_current_round(game_id)
            state = GameManager.get_game_state(game_id)
            
            # Broadcast zur nächsten Runde
            socketio.emit('round_started', {
                'round_number': current_round.round_number,
                'game_state': state
            }, room=game_id)
            
            return jsonify({
                'success': True,
                'has_next': True,
                'next_round': current_round.round_number
            }), 200
        else:
            # Spiel beendet
            results = GameManager.get_game_results(game_id)
            
            socketio.emit('game_ended', results, room=game_id)
            
            return jsonify({
                'success': True,
                'has_next': False,
                'results': results
            }), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ============== WebSocket-Events ==============

@socketio.on('connect')
def handle_connect():
    """Spieler verbunden"""
    print(f'Client connected: {request.sid}')
    emit('response', {'data': 'Connected'})


@socketio.on('join_game_room')
def on_join_game(data):
    """Trete Spiel-Room bei"""
    game_id = data.get('game_id')
    player_id = data.get('player_id')

    join_room(game_id)
    print(f'Player {player_id} joined room {game_id}')

    emit('message', {
        'data': f'Spieler hat den Raum betreten'
    }, room=game_id)


@socketio.on('disconnect')
def handle_disconnect():
    """Spieler getrennt"""
    print(f'Client disconnected: {request.sid}')


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
