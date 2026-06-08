from flask import Flask, render_template
from flask_compress import Compress

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 31536000
Compress(app)


@app.after_request
def add_cache_headers(response):
    if response.content_type in ('text/css', 'application/javascript',
                                  'image/png', 'image/jpeg'):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return response


@app.route('/')
def start():
    return render_template('start.html')


@app.route('/play')
def play():
    return render_template('wait_screen.html')


@app.route('/results')
def results():
    return render_template('results.html')


# Die Vektor-Basemap (static/data/basemap.pmtiles) wird vom statischen
# Flask-Handler ausgeliefert, der HTTP-Range-Requests unterstuetzt - genau
# das, was PMTiles im Browser benoetigt. Keine eigene Tile-Route mehr noetig.

if __name__ == '__main__':

    # threaded=True: MapLibre/PMTiles feuert beim Zoomen viele parallele
    # Range-Requests auf basemap.pmtiles ab. Der Default-Dev-Server ist
    # single-threaded und lehnt gleichzeitige Verbindungen ab (ERR_CONNECTION
    # _REFUSED) - mit Threads werden sie nebenlaeufig bedient.
    app.run(host='0.0.0.0', port=8080, debug=True, threaded=True)
