import mimetypes

from flask import Flask, render_template, send_file
from flask_compress import Compress

mimetypes.add_type('application/javascript', '.mjs')

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0
Compress(app)


@app.after_request
def add_cache_headers(response):
    if response.content_type in ('text/css', 'application/javascript'):
        response.headers['Cache-Control'] = 'no-cache'
    return response

@app.route('/')
def start():
    return render_template('start.html')


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
    # threaded=True: MapLibre/PMTiles feuert beim Zoomen viele parallele
    # Range-Requests auf basemap.pmtiles ab. Der Default-Dev-Server ist
    # single-threaded und lehnt gleichzeitige Verbindungen ab (ERR_CONNECTION
    # _REFUSED) - mit Threads werden sie nebenlaeufig bedient.
    app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)
