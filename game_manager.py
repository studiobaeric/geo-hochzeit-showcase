"""Spiellogik und API-Handler"""
import json
import uuid
from datetime import datetime
from db import db, Game, Player, Round, GuessResult
import secrets
from math import radians, sin, cos, sqrt, atan2


def calculate_distance(lat1, lon1, lat2, lon2):
    """Haversine-Formel: Distanz zwischen zwei Koordinaten in km"""
    R = 6371
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1-a))
    return R * c


def get_photos():
    """Lade Photos aus JSON"""
    try:
        with open('static/data/photos.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"ERROR loading photos.json: {e}")
        return []


class GameManager:
    """Spiellogik und State-Management"""

    @staticmethod
    def create_game():
        """Erstelle neue Spielsession"""
        game = Game(
            id=str(uuid.uuid4()),
            moderator_token=secrets.token_urlsafe(32)
        )
        db.session.add(game)
        db.session.commit()
        return game

    @staticmethod
    def get_game(game_id):
        """Hole Spielsession"""
        return Game.query.get(game_id)

    @staticmethod
    def add_player(game_id, player_name):
        """Füge Spieler zu Spiel hinzu"""
        game = Game.query.get(game_id)
        if not game:
            return None

        # Definiere Farben für Spieler-Marker
        colors = ['blue', 'green', 'purple', 'orange', 'yellow', 'pink']
        player_color = colors[len(game.players) % len(colors)]

        player = Player(
            id=str(uuid.uuid4()),
            game_id=game_id,
            name=player_name,
            color=player_color
        )
        db.session.add(player)
        db.session.commit()
        return player

    @staticmethod
    def start_game(game_id):
        """Starte Spiel und initialiesiere Runden"""
        game = Game.query.get(game_id)
        if not game or game.status != 'waiting':
            return False

        photos = get_photos()
        game.started_at = datetime.utcnow()
        game.status = 'active'

        # Erstelle Runden für jedes Foto
        for idx, photo in enumerate(photos):
            round_obj = Round(
                id=str(uuid.uuid4()),
                game_id=game_id,
                round_number=idx + 1,
                photo_id=photo['id'],
                status='waiting' if idx > 0 else 'active'  # Erste Runde ist aktiv
            )
            db.session.add(round_obj)

        db.session.commit()
        return True

    @staticmethod
    def submit_guess(game_id, player_id, round_number, latitude, longitude):
        """Speichere Tipp eines Spielers"""
        game = Game.query.get(game_id)
        player = Player.query.get(player_id)
        round_obj = Round.query.filter_by(game_id=game_id, round_number=round_number).first()

        if not (game and player and round_obj):
            return None

        # Hole tatsächliche Location aus photos.json
        photos = get_photos()
        photo = next((p for p in photos if p['id'] == round_obj.photo_id), None)

        if not photo:
            return None

        # Berechne Distanz
        actual_lat = photo['location']['lat']
        actual_lng = photo['location']['lng']
        distance = calculate_distance(latitude, longitude, actual_lat, actual_lng)

        # Speichere Tipp
        guess = GuessResult(
            id=str(uuid.uuid4()),
            round_id=round_obj.id,
            player_id=player_id,
            latitude=latitude,
            longitude=longitude,
            distance_km=distance
        )
        db.session.add(guess)

        # Aktualisiere Spieler-Gesamtdistanz
        player.total_distance += distance

        db.session.commit()
        return guess

    @staticmethod
    def get_game_results(game_id):
        """Hole Ergebnisse für ein Spiel"""
        game = Game.query.get(game_id)
        if not game:
            return None

        photos = get_photos()
        results = {
            'game_id': game_id,
            'players': [p.to_dict() for p in game.players],
            'rounds': [],
            'total_distance': sum(p.total_distance for p in game.players) / len(game.players) if game.players else 0
        }

        # Hole Daten zu jedem Runde
        for round_obj in sorted(game.rounds, key=lambda r: r.round_number):
            photo = next((p for p in photos if p['id'] == round_obj.photo_id), None)

            round_data = {
                'round_number': round_obj.round_number,
                'photo': photo,
                'guesses': []
            }

            # Sammle Tipps für diese Runde
            for guess in round_obj.guesses:
                round_data['guesses'].append({
                    'player_id': guess.player_id,
                    'player_name': guess.player.name,
                    'player_color': guess.player.color,
                    'latitude': guess.latitude,
                    'longitude': guess.longitude,
                    'distance_km': guess.distance_km
                })

            results['rounds'].append(round_data)

        return results

    @staticmethod
    def get_game_state(game_id):
        """Hole aktuellen Spielzustand für Live-Updates"""
        game = Game.query.get(game_id)
        if not game:
            return None

        photos = get_photos()

        return {
            'game_id': game_id,
            'status': game.status,
            'players': [{'id': p.id, 'name': p.name, 'color': p.color} for p in game.players],
            'photos': photos,
            'rounds': [r.to_dict() for r in sorted(game.rounds, key=lambda r: r.round_number)]
        }

    @staticmethod
    def end_game(game_id):
        """Beende Spiel"""
        game = Game.query.get(game_id)
        if not game:
            return False

        game.status = 'completed'
        game.ended_at = datetime.utcnow()
        db.session.commit()
        return True

    @staticmethod
    def get_current_round(game_id):
        """Hole aktuelle aktive Runde"""
        round_obj = Round.query.filter_by(game_id=game_id, status='active').first()
        return round_obj
    
    @staticmethod
    def get_round_status(game_id):
        """Hole Status der aktuellen Runde (wieviele Spieler haben getippt)"""
        game = Game.query.get(game_id)
        current_round = GameManager.get_current_round(game_id)
        
        if not current_round:
            return None
        
        total_players = len(game.players)
        guesses_submitted = len(current_round.guesses)
        
        return {
            'round_id': current_round.id,
            'round_number': current_round.round_number,
            'total_players': total_players,
            'guesses_submitted': guesses_submitted,
            'all_ready': guesses_submitted >= total_players,
            'players_remaining': total_players - guesses_submitted
        }
    
    @staticmethod
    def progress_to_next_round(game_id):
        """Gehe zur nächsten Runde"""
        game = Game.query.get(game_id)
        current_round = GameManager.get_current_round(game_id)
        
        if not current_round:
            return False
        
        # Markiere aktuelle Runde als completed
        current_round.status = 'completed'
        current_round.ended_at = datetime.utcnow()
        
        # Finde nächste Runde
        next_round = Round.query.filter_by(
            game_id=game_id,
            status='waiting'
        ).order_by(Round.round_number).first()
        
        if next_round:
            next_round.status = 'active'
            next_round.started_at = datetime.utcnow()
            db.session.commit()
            return True
        else:
            # Spiel beendet
            game.status = 'completed'
            game.ended_at = datetime.utcnow()
            db.session.commit()
            return False
