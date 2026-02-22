from flask import Flask, render_template, send_from_directory
import os

app = Flask(__name__)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/tiles/<int:z>/<int:x>/<int:y>.png')
def tiles(z, x, y):
    """Serve offline map tiles"""
    tile_dir = os.path.join('static', 'tiles', str(z), str(x))
    return send_from_directory(tile_dir, f'{y}.png')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
