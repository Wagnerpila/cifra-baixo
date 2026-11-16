"""Servidor da ferramenta de padrões no braço do baixo."""
import os, re, json, uuid, tempfile, threading, hmac
from urllib.parse import urlparse
from flask import Flask, request, jsonify, send_from_directory, Response
import cifra_padrao as cp

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:
    pass

DATA = os.environ.get('DATA_DIR', '/data')
STORE = os.path.join(DATA, 'songs.json')
USER = os.environ.get('CIFRA_USER', 'baixo')
PASS = os.environ.get('CIFRA_PASS', '')
LOCK = threading.Lock()
DEF_GROUP = 'Momentos Joam'
ALLOWED_EXT = {'.docx', '.pdf', '.png', '.jpg', '.jpeg', '.webp', '.bmp', '.heic', '.txt'}

app = Flask(__name__, static_folder='static', static_url_path='/static')
app.config['MAX_CONTENT_LENGTH'] = 40 * 1024 * 1024


def load():
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(STORE):
        seedf = os.path.join(os.path.dirname(__file__), 'seed', 'joam.json')
        seed = json.load(open(seedf, encoding='utf-8')) if os.path.exists(seedf) else []
        for s in seed: s['id'] = uuid.uuid4().hex[:10]
        save(seed)
        return seed
    songs = json.load(open(STORE, encoding='utf-8'))
    for s in songs: s.setdefault('group', DEF_GROUP)
    return songs


def clean_group(g):
    g = re.sub(r'\s+', ' ', (g or '')).strip()[:60]
    return g or DEF_GROUP


def save(songs):
    tmp = STORE + '.tmp'
    json.dump(songs, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False)
    os.replace(tmp, STORE)


@app.before_request
def auth():
    if request.path == '/healthz' or not PASS: return None
    a = request.authorization
    if a and hmac.compare_digest(a.username or '', USER) and hmac.compare_digest(a.password or '', PASS): return None
    return Response('Acesso restrito', 401, {'WWW-Authenticate': 'Basic realm="Padroes no braco"'})


@app.get('/healthz')
def healthz(): return 'ok'


@app.get('/')
def index(): return send_from_directory('static', 'index.html')


@app.get('/api/songs')
def songs():
    with LOCK: return jsonify(load())


def host_ok(url):
    h = (urlparse(url).hostname or '').lower()
    return urlparse(url).scheme in ('http', 'https') and (h == 'cifraclub.com.br' or h.endswith('.cifraclub.com.br') or h == 'cifraclub.com' or h.endswith('.cifraclub.com'))


@app.post('/api/analisar')
def analisar():
    found, errors = [], []
    with tempfile.TemporaryDirectory() as d:
        for f in request.files.getlist('arquivos'):
            name = os.path.basename(f.filename or 'musica')
            ext = os.path.splitext(name)[1].lower()
            if ext not in ALLOWED_EXT:
                errors.append(f'{name}: formato não suportado'); continue
            p = os.path.join(d, re.sub(r'[^\w.\- ]', '_', name))
            f.save(p)
            try:
                if ext == '.heic':
                    from PIL import Image
                    png = p + '.png'; Image.open(p).convert('RGB').save(png); p = png
                found += cp.analyze_songs(cp.load_inputs([p]))
            except Exception as e:
                errors.append(f'{name}: {type(e).__name__}: {str(e)[:120]}')
        url = (request.form.get('url') or '').strip()
        if url:
            if not host_ok(url): errors.append('Link: só aceito links do Cifra Club')
            else:
                try: found += cp.analyze_songs(cp.load_inputs([url]))
                except Exception as e: errors.append(f'Link: {type(e).__name__}: {str(e)[:220]}')
        text = (request.form.get('texto') or '').strip()
        if text:
            try: found += cp.analyze_songs(cp.songs_from_text(text, request.form.get('titulo') or 'Música colada'))
            except Exception as e: errors.append(f'Texto: {type(e).__name__}')
    if not found and not errors: errors.append('Nada para analisar. Envie um arquivo, link ou texto.')
    if not found and errors: return jsonify({'added': [], 'errors': errors}), 422
    with LOCK:
        songs = load()
        grupo = clean_group(request.form.get('grupo'))
        for s in found: s['id'] = uuid.uuid4().hex[:10]; s['group'] = grupo
        songs.extend(found); save(songs)
    return jsonify({'added': [s['id'] for s in found], 'errors': errors})


@app.post('/api/remover')
def remover():
    sid = (request.get_json(silent=True) or {}).get('id')
    with LOCK:
        songs = load(); new = [s for s in songs if s.get('id') != sid]
        if len(new) == len(songs): return jsonify({'ok': False}), 404
        save(new)
    return jsonify({'ok': True})


@app.post('/api/mover')
def mover():
    j = request.get_json(silent=True) or {}
    sid, g = j.get('id'), clean_group(j.get('group'))
    with LOCK:
        songs = load(); hit = [s for s in songs if s.get('id') == sid]
        if not hit: return jsonify({'ok': False}), 404
        hit[0]['group'] = g; save(songs)
    return jsonify({'ok': True})
