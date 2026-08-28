import json
import mimetypes
import os
import socket
import sys

from flask import Flask, jsonify, render_template, send_file, url_for
from flask_compress import Compress

import game_state
import i18n
from game_state import bp as api_bp
from map_build import bp as map_bp
from photo_config import bp as photos_bp

mimetypes.add_type('application/javascript', '.mjs')

# Released binaries (see tools/build_release.py) ship templates/ and static/
# as plain folders next to the executable rather than embedding them, so
# Flask needs to look them up relative to the executable instead of this
# script's location when running from a PyInstaller build.
if getattr(sys, 'frozen', False):
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _read_version():
    version_file = os.path.join(_BASE_DIR, 'VERSION')
    if os.path.exists(version_file):
        with open(version_file, encoding='utf-8') as f:
            return f.read().strip()
    return 'dev'


APP_VERSION = _read_version()

# Port the game server listens on (see app.run() at the bottom) - also
# exposed via /api/host-info so the config menu can show it as part of the
# join URL/QR code.
PORT = 8080


def _detect_lan_ip():
    """Best-effort LAN IP of this machine, for the config menu's host-info
    QR code so guests on another device (e.g. a tablet) can join without
    typing the address by hand.

    Opens a UDP "connection" to a public address - no packets are actually
    sent, this is just how the OS is asked which local interface/IP it
    would use to reach that destination. Falls back to localhost if the
    machine has no network route (e.g. offline).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))
        return sock.getsockname()[0]
    except OSError:
        return '127.0.0.1'
    finally:
        sock.close()


app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, 'templates'),
    static_folder=os.path.join(_BASE_DIR, 'static'),
)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
Compress(app)
app.register_blueprint(api_bp)
app.register_blueprint(map_bp)
app.register_blueprint(photos_bp)


@app.context_processor
def inject_i18n():
    """Makes `t(key)`, `locale` and `i18n_json` available in every
    template, per #98. `t` translates a dotted key into the currently
    configured UI language (server-side, so the very first response
    already has the right strings - no flash of German while JS loads).
    `i18n_json` is the same locale's full string tree (pre-merged with the
    German fallback) as a JSON string, meant to be embedded once per page
    as `window.I18N` so static/js/i18n.js's t() can translate strings that
    are only assembled at runtime in JS, without a separate fetch.
    """
    locale = game_state.get_locale()
    return {
        'locale': locale,
        't': lambda key: i18n.translate(locale, key),
        'i18n_json': json.dumps(i18n.translations_for(locale)),
        'available_locales': [
            (code, i18n.LOCALE_NAMES[code], url_for('static', filename=f'img/flags/{i18n.LOCALE_FLAGS[code]}'))
            for code in i18n.SUPPORTED_LOCALES
        ],
    }


@app.route('/api/version')
def version():
    return jsonify(version=APP_VERSION)


@app.route('/api/host-info')
def host_info():
    ip = _detect_lan_ip()
    return jsonify(ip=ip, port=PORT, url=f'http://{ip}:{PORT}/')


@app.after_request
def add_cache_headers(response):
    # response.content_type includes a "; charset=..." suffix for text
    # responses (added by Flask/Werkzeug), so it never equals a bare
    # mimetype - response.mimetype is the same value with that stripped.
    # Both 'application/javascript' (legacy) and 'text/javascript' (what
    # Python's mimetypes module actually guesses for .js on most current
    # platforms) are checked since either can show up depending on the
    # platform's mimetypes database.
    if response.mimetype in ('text/css', 'application/javascript', 'text/javascript'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/')
def start():
    return render_template('start.html')


@app.route('/config')
def config():
    return render_template('config.html')


@app.route('/game')
def game():
    return render_template('game.html')

@app.route('/moderator')
def moderator():
    return render_template('moderator.html')


@app.route('/results')
def results():
    return render_template('results.html')


@app.route('/end_of_game')
def end_of_game():
    return render_template('end_of_game.html')


# Die Vektor-Basemap (static/data/basemap.pmtiles) wird vom statischen
# Flask-Handler ausgeliefert, der HTTP-Range-Requests unterstuetzt - genau
# das, was PMTiles im Browser benoetigt. Keine eigene Tile-Route mehr noetig.

if __name__ == '__main__':
    # In gebauten Binaries (siehe tools/build_release.py) gibt es keine
    # Konsole zum Ablesen der URL, und Flasks Debug-Reloader wuerde den
    # PyInstaller-Onefile-Prozess in einer Schleife neu starten - daher
    # dort debug=False und stattdessen automatisch den Browser oeffnen.
    is_frozen = getattr(sys, 'frozen', False)
    if is_frozen:
        import webbrowser
        webbrowser.open(f'http://localhost:{PORT}')

    # threaded=True: MapLibre/PMTiles feuert beim Zoomen viele parallele
    # Range-Requests auf basemap.pmtiles ab. Der Default-Dev-Server ist
    # single-threaded und lehnt gleichzeitige Verbindungen ab (ERR_CONNECTION
    # _REFUSED) - mit Threads werden sie nebenlaeufig bedient.
    app.run(host='0.0.0.0', port=PORT, debug=not is_frozen, threaded=True)
