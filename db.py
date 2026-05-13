"""
Datenbankmodelle für das Multiplayer-Geoguesser-Spiel
"""
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import uuid

db = SQLAlchemy()


class Game(db.Model):
    """Repräsentiert eine Spielsession"""
    __tablename__ = 'games'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    ended_at = db.Column(db.DateTime)
    status = db.Column(db.String(20), default='waiting')  # waiting, active, completed
    moderator_token = db.Column(db.String(64), unique=True)

    players = db.relationship('Player', backref='game', lazy=True, cascade='all, delete-orphan')
    rounds = db.relationship('Round', backref='game', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'ended_at': self.ended_at.isoformat() if self.ended_at else None,
            'status': self.status,
            'player_count': len(self.players)
        }


class Player(db.Model):
    """Repräsentiert einen Spieler in einer Spielsession"""
    __tablename__ = 'players'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    game_id = db.Column(db.String(36), db.ForeignKey('games.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(20))  # Für Marker-Farben
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)
    total_distance = db.Column(db.Float, default=0.0)

    guesses = db.relationship('GuessResult', backref='player', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'color': self.color,
            'total_distance': self.total_distance,
            'joined_at': self.joined_at.isoformat()
        }


class Round(db.Model):
    """Repräsentiert eine Runde in einem Spiel"""
    __tablename__ = 'rounds'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    game_id = db.Column(db.String(36), db.ForeignKey('games.id'), nullable=False)
    round_number = db.Column(db.Integer, nullable=False)
    photo_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='waiting')  # waiting, active, completed
    started_at = db.Column(db.DateTime, default=datetime.utcnow)
    ended_at = db.Column(db.DateTime)

    guesses = db.relationship('GuessResult', backref='round', lazy=True, cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'round_number': self.round_number,
            'photo_id': self.photo_id,
            'status': self.status,
            'started_at': self.started_at.isoformat(),
            'ended_at': self.ended_at.isoformat() if self.ended_at else None
        }


class GuessResult(db.Model):
    """Speichert die Tipps der Spieler pro Runde"""
    __tablename__ = 'guess_results'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    round_id = db.Column(db.String(36), db.ForeignKey('rounds.id'), nullable=False)
    player_id = db.Column(db.String(36), db.ForeignKey('players.id'), nullable=False)
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)
    distance_km = db.Column(db.Float)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'player_id': self.player_id,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'distance_km': self.distance_km,
            'created_at': self.created_at.isoformat()
        }

