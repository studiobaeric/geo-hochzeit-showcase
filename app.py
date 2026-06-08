from flask import Flask, render_template

app = Flask(__name__)


@app.route('/')
def start():
    return render_template('start.html')


@app.route('/play')
def play():
    return render_template('game.html')


@app.route('/results')
def results():
    return render_template('results.html')


# Die Vektor-Basemap (static/data/basemap.pmtiles) wird vom statischen
# Flask-Handler ausgeliefert, der HTTP-Range-Requests unterstuetzt - genau
# das, was PMTiles im Browser benoetigt. Keine eigene Tile-Route mehr noetig.

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=True)
