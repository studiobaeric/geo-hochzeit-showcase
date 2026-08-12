import mimetypes
import os
import sys

from flask import Flask, jsonify, render_template, send_file
from flask_compress import Compress

from game_state import bp as api_bp
from map_build import bp as map_bp

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

app = Flask(
    __name__,
    template_folder=os.path.join(_BASE_DIR, 'templates'),
    static_folder=os.path.join(_BASE_DIR, 'static'),
)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
Compress(app)
app.register_blueprint(api_bp)
app.register_blueprint(map_bp)


@app.route('/api/version')
def version():
    return jsonify(version=APP_VERSION)


@app.after_request
def add_cache_headers(response):
    if response.content_type in ('text/css', 'application/javascript'):
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
        webbrowser.open('http://localhost:8080')

    # threaded=True: MapLibre/PMTiles feuert beim Zoomen viele parallele
    # Range-Requests auf basemap.pmtiles ab. Der Default-Dev-Server ist
    # single-threaded und lehnt gleichzeitige Verbindungen ab (ERR_CONNECTION
    # _REFUSED) - mit Threads werden sie nebenlaeufig bedient.
    app.run(host='0.0.0.0', port=8080, debug=not is_frozen, threaded=True)
