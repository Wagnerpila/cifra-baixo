#!/usr/bin/env python3
"""
cifra_padrao.py - Le cifras (txt, docx, pdf, imagem/print, link) e escreve o
PADRAO da musica em graus do campo harmonico, separado em intro / verso /
pre-refrao / refrao / ponte / final.

Uso:
  python3 cifra_padrao.py arquivo.docx -o saida          # songbook com varias musicas
  python3 cifra_padrao.py cifra.pdf print.png musica.txt -o saida
  python3 cifra_padrao.py https://www.cifraclub.com.br/artista/musica/ -o saida
Gera: saida.json (para o visualizador do braco) e saida.md (padroes em texto).
"""
import re, sys, json, os, argparse, unicodedata
from difflib import SequenceMatcher
from collections import Counter

# ----------------------------------------------------------------- teoria
LETTER_PC = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
LETTERS = 'CDEFGAB'
SHARP_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
FLAT_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
FLAT_TONICS_MAJ = {5, 10, 3, 8, 1}             # F Bb Eb Ab Db (F# maior fica com sustenidos)
FLAT_TONICS_MIN = {2, 7, 0, 5, 10, 3}          # Dm Gm Cm Fm Bbm Ebm

MAJ_STEPS = [0, 2, 4, 5, 7, 9, 11]
MIN_STEPS = [0, 2, 3, 5, 7, 8, 10]


def pc_of(name):
    pc = LETTER_PC[name[0].upper()]
    for ch in name[1:]:
        if ch in '#♯': pc += 1
        elif ch in 'b♭': pc -= 1
    return pc % 12


def note_name(pc, flats):
    return (FLAT_NAMES if flats else SHARP_NAMES)[pc % 12]


def key_uses_flats(tonic_pc, mode):
    return tonic_pc in (FLAT_TONICS_MAJ if mode == 'M' else FLAT_TONICS_MIN)


def spell_scale(tonic_name, mode):
    """Escala com grafia correta (cada letra uma vez)."""
    steps = MAJ_STEPS if mode == 'M' else MIN_STEPS
    t = pc_of(tonic_name)
    li = LETTERS.index(tonic_name[0].upper())
    out = []
    for i, s in enumerate(steps):
        L = LETTERS[(li + i) % 7]
        diff = ((t + s) - LETTER_PC[L] + 6) % 12 - 6
        out.append(L + ('#' * diff if diff > 0 else 'b' * -diff))
    return out


CHORD_RE = re.compile(r"^([A-G](?:#|b|♯|♭)?)([^/\s]*?)(?:/([A-G](?:#|b)?))?$")
SUF_OK = re.compile(r"^(?:m|min|M|maj|dim|aug|sus|add|\+|-|°|º|ø|[0-9]|#|b|\(|\)|,|/)*$")


def parse_chord(tok):
    tok = tok.strip()
    m = CHORD_RE.match(tok)
    if not m: return None
    root, suf, bass = m.groups()
    if not SUF_OK.match(suf): return None
    if suf.startswith('b') and not re.match(r"^b[0-9]", suf): return None
    low = suf.lower()
    if re.match(r"^(dim|°|º|ø)", suf) or 'm7b5' in low or 'm7(b5)' in low:
        q = 'd'
    elif re.match(r"^(aug|\+)", suf) or re.match(r"^7\+", suf):
        q = 'a'
    elif re.match(r"^(maj|M)", suf):
        q = 'M'
    elif re.match(r"^(m|min|-)", suf):
        q = 'm'
    elif low.startswith('sus'):
        q = 's'
    else:
        q = 'M'
    dom7 = bool(re.match(r"^7(?!M)", suf)) or bool(re.match(r"^(9|11|13)$", suf) and False)
    return {'n': tok, 'r': pc_of(root), 'rn': root, 'q': q, 's': suf,
            'b': pc_of(bass) if bass else None, 'bn': bass, 'd7': dom7}


MARKERS = {'|', '-', '/', '(bis)', 'bis', '(2x)', '2x', 'x2', '(x2)', '(3x)', '3x', 'x3', '...', '–', '||', '%'}


def strip_tok(t):
    return t.strip('()[]|,;:')


def tokens_with_pos(line):
    return [(m.group(), m.start()) for m in re.finditer(r"\S+", line)]


def chord_line_info(line):
    """Se for linha de acordes devolve [(chord, col)], senao None."""
    toks = tokens_with_pos(line)
    if not toks: return None
    out = []
    for t, pos in toks:
        if t.lower() in MARKERS or re.fullmatch(r"\(?\d+x\)?|\(?x\d+\)?|[|/\-–]+", t.lower()):
            continue
        c = parse_chord(strip_tok(t))
        if not c: return None
        out.append((c, pos))
    return out or None


SEC_RE = re.compile(
    r"^\s*[\[\(]?\s*(intro(?:du[cç][aã]o)?|verso|estrofe|primeira parte|segunda parte|terceira parte|"
    r"parte\s*\d|pr[eé][- ]?refr[aã]o|refr[aã]o(?: final)?|coro|ponte|solo|interl[uú]dio|final|outro|"
    r"verse|chorus|pre-chorus|bridge)\b([^\]\)]*)[\]\)]?\s*:?\s*(.*)$", re.I)


def norm_sec(label):
    l = label.lower()
    if l.startswith('intro'): return 'Intro'
    if re.match(r'pr[eé][- ]?(refr|chorus)', l): return 'Pré-refrão'
    if l.startswith(('refr', 'coro', 'chorus')): return 'Refrão'
    if l.startswith(('verso', 'estrofe', 'primeira', 'segunda', 'terceira', 'parte', 'verse')): return 'Verso'
    if l.startswith(('ponte', 'bridge')): return 'Ponte'
    if l.startswith('solo') or l.startswith('interl'): return 'Solo'
    if l.startswith(('final', 'outro')): return 'Final'
    return label.title()


def classify(line):
    """-> (kind, data). kinds: blank, meta, marker, chords, lyric"""
    s = line.replace('\xa0', ' ').rstrip()
    if not s.strip(): return 'blank', None
    m = re.match(r"^\s*tom\s*:\s*([A-G][#b]?m?)\b", s, re.I)
    if m: return 'meta', {'tom': m.group(1)}
    m = re.match(r"^\s*(?:capotraste|capo)\b[^0-9]*(\d+)", s, re.I)
    if m: return 'meta', {'capo': int(m.group(1))}
    m = SEC_RE.match(s)
    if m:
        g2 = m.group(2)
        if re.fullmatch(r"\s*(\d+|final|\(.*\))?\s*", g2, re.I):
            rest = m.group(3).strip()
        else:
            rest = (g2.lstrip(' :') + ' ' + m.group(3)).strip()
        info = chord_line_info(rest) if rest else None
        if not rest or info:
            return 'marker', {'label': norm_sec(m.group(1)), 'chords': info}
    info = chord_line_info(s)
    if info: return 'chords', info
    return 'lyric', s.strip('\n')


# ----------------------------------------------------------------- musicas
def parse_song_lines(lines, title='', artist=''):
    """Transforma linhas cruas em estrutura de blocos."""
    items = []
    meta = {}
    for ln in lines:
        k, d = classify(ln)
        if k == 'meta': meta.update(d); continue
        items.append((k, d, ln.replace('\xa0', ' ')))
    # blocos
    blocks, cur = [], None

    def close():
        nonlocal cur
        if cur and cur['lines']: blocks.append(cur)
        cur = None

    def new(label=None):
        nonlocal cur
        close(); cur = {'label': label, 'lines': []}

    i = 0
    while i < len(items):
        k, d, raw = items[i]
        if k == 'blank':
            close(); i += 1; continue
        if k == 'marker':
            new(d['label'])
            if d['chords']:
                cur['lines'].append({'t': 'chords', 'chords': [c for c, _ in d['chords']]})
                if d['label'] in ('Intro', 'Solo', 'Final', 'Outro'): close()
            i += 1; continue
        if cur is None: new()
        if k == 'chords':
            nxt = items[i + 1] if i + 1 < len(items) else None
            if nxt and nxt[0] == 'lyric':
                lyric = nxt[2].strip('\n')
                cl = [(c, p) for c, p in d]
                cur['lines'].append({'t': 'pair', 'chords': cl, 'lyric': lyric})
                i += 2; continue
            cur['lines'].append({'t': 'chords', 'chords': [c for c, _ in d]})
        else:
            cur['lines'].append({'t': 'lyric', 'lyric': raw.strip()})
        i += 1
    close()
    return {'title': title, 'artist': artist, 'meta': meta, 'blocks': blocks}


def block_chords(b):
    out = []
    for l in b['lines']:
        if l['t'] == 'pair': out += [c for c, _ in l['chords']]
        elif l['t'] == 'chords': out += l['chords']
    return out


def block_lyric(b):
    txt = ' '.join(l['lyric'] for l in b['lines'] if l['t'] in ('pair', 'lyric'))
    txt = unicodedata.normalize('NFD', txt.lower())
    txt = ''.join(ch for ch in txt if unicodedata.category(ch) != 'Mn')
    return re.sub(r"[^a-z0-9 ]", '', txt).strip()


# ----------------------------------------------------------------- tom
def triads(tonic, mode):
    """triades diatonicas (root_pc, quality) com graus 0..6"""
    steps = MAJ_STEPS if mode == 'M' else MIN_STEPS
    q = ['M', 'm', 'm', 'M', 'M', 'm', 'd'] if mode == 'M' else ['m', 'd', 'M', 'm', 'm', 'M', 'M']
    return [((tonic + s) % 12, qq) for s, qq in zip(steps, q)]


def key_score(chords, tonic, mode, declared=None):
    diat = triads(tonic, mode)
    dset = {(r, q) for r, q in diat}
    roots = {r for r, _ in diat}
    extra = set()
    if mode == 'm':                       # menor harmonica: V maior e vii dim
        extra = {((tonic + 7) % 12, 'M'), ((tonic + 11) % 12, 'd')}
    sc = 0.0
    for c in chords:
        r, q = c['r'], ('M' if c['q'] == 's' else c['q'])
        if (r, q) in dset: sc += 2
        elif (r, q) in extra: sc += 1.6
        elif r in roots: sc += 0.6
        else: sc -= 1
    if chords:
        t = (tonic, 'M' if mode == 'M' else 'm')
        f, l = chords[0], chords[-1]
        if (f['r'], f['q']) == t: sc += 1.5
        if (l['r'], l['q']) == t: sc += 2.5
        cnt = Counter((c['r'], c['q']) for c in chords)
        if cnt.most_common(1)[0][0] == t: sc += 1.0
        sc += min(3.0, 0.5 * cnt.get(t, 0))
        if cnt.get(t, 0) == 0: sc -= 1.5
    if declared and declared == (tonic, mode): sc += 2
    return sc


def parse_declared(t):
    if not t: return None
    m = re.match(r"([A-G][#b]?)(m?)", t)
    if not m: return None
    return (pc_of(m.group(1)), 'm' if m.group(2) else 'M')


def detect_key(chords, declared_txt=None):
    declared = parse_declared(declared_txt)
    res = []
    for t in range(12):
        for mode in 'Mm':
            res.append((key_score(chords, t, mode, declared), t, mode))
    res.sort(key=lambda x: -x[0])
    best = res[0]
    # tonica com grafia: usa a grafia do acorde que tem esse root (ex. Bb) senao pela armadura
    return res[:4]


def tonic_spelling(tonic, mode, chords):
    for c in chords:
        if c['r'] == tonic and c['q'] in ('M', 'm', 's'):
            return c['rn']
    return note_name(tonic, key_uses_flats(tonic, mode))


# ----------------------------------------------------------------- graus
ROM = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII']
MAJ_DEG = {0: ('', 0), 1: ('b', 1), 2: ('', 1), 3: ('b', 2), 4: ('', 2), 5: ('', 3),
           6: ('#', 3), 7: ('', 4), 8: ('b', 5), 9: ('', 5), 10: ('b', 6), 11: ('', 6)}
MIN_DEG = {0: ('', 0), 1: ('b', 1), 2: ('', 1), 3: ('', 2), 4: ('#', 2), 5: ('', 3),
           6: ('#', 3), 7: ('', 4), 8: ('', 5), 9: ('#', 5), 10: ('', 6), 11: ('#', 6)}


def suffix_rest(c):
    """parte da cifra apos a qualidade basica (7, 9, sus4, add9, 7M ...)"""
    s = c['s']
    s = re.sub(r"^(min|m(?!aj)|-)", '', s) if c['q'] == 'm' else s
    s = re.sub(r"^(dim|°|º)", '', s) if c['q'] == 'd' else s
    return s


def degree_label(c, tonic, mode):
    iv = (c['r'] - tonic) % 12
    acc, idx = (MAJ_DEG if mode == 'M' else MIN_DEG)[iv]
    base = acc + ROM[idx]
    q = c['q']
    suf = suffix_rest(c)
    if q == 'm': base += 'm'
    elif q == 'd': base += '°'
    elif q == 'a': base += '+'
    elif q == 's': base += ''
    if q == 'd' and 'm7b5' in c['s'].lower(): base = base.replace('°', '') + 'ø'
    base += suf if q not in ('d',) else ''
    if c['b'] is not None and c['b'] != c['r']:
        biv = (c['b'] - tonic) % 12
        bacc, bidx = (MAJ_DEG if mode == 'M' else MIN_DEG)[biv]
        base += '/' + bacc + str(bidx + 1)
    return base


def diatonic_status(c, tonic, mode):
    r, q = c['r'], ('M' if c['q'] == 's' else c['q'])
    d = set(triads(tonic, mode))
    if mode == 'm': d |= {((tonic + 7) % 12, 'M'), ((tonic + 11) % 12, 'd')}
    return (r, q) in d


def compress(seq):
    out = []
    for x in seq:
        if not out or out[-1] != x: out.append(x)
    return out


def find_cycle(seq):
    n = len(seq)
    for p in range(1, n // 2 + 1):
        if n < 2 * p: break
        ok = sum(1 for i in range(n) if seq[i] == seq[i % p])
        if ok / n >= 0.9: return seq[:p]
    return None


# ----------------------------------------------------------------- secoes
def sim(a, b):
    return SequenceMatcher(None, a, b).ratio() if a and b else 0


def label_blocks(song, degs_of):
    blocks = song['blocks']
    n = len(blocks)
    for b in blocks:
        b['lyr'] = block_lyric(b)
        b['deg'] = degs_of(b)
        b['src'] = 'marcado' if b['label'] else None
    # 1) Intro implícita: primeiro bloco so com acordes
    if blocks and not blocks[0]['label'] and all(l['t'] == 'chords' for l in blocks[0]['lines']):
        blocks[0]['label'] = 'Intro'; blocks[0]['src'] = 'só acordes'
    for b in blocks:
        if not b['label'] and not b['deg']:
            b['label'] = 'Letra sem cifra'; b['src'] = 'sem acordes'
    # 2) repeticao de letra
    idx = [i for i, b in enumerate(blocks) if b['lyr'] and len(b['lyr']) >= 8 and b['deg']]
    group = {}
    gid = 0
    for i in idx:
        for j in [x for x in idx if x < i]:
            if sim(blocks[i]['lyr'], blocks[j]['lyr']) >= 0.8:
                group[i] = group[j]; break
        else:
            group[i] = gid; gid += 1
    cnt = Counter(group.values())
    rep = [g for g, c in cnt.items() if c >= 2]
    chorus_group = None
    labeled_ref = [i for i, b in enumerate(blocks) if b['label'] == 'Refrão']
    if labeled_ref and labeled_ref[0] in group:
        chorus_group = group[labeled_ref[0]]
    elif rep:
        chorus_group = max(rep, key=lambda g: (cnt[g], -min(i for i in group if group[i] == g)))
    ref_src = 'letra repetida'
    if chorus_group is None and not labeled_ref:
        t = re.sub(r"[^a-z0-9 ]", '', unicodedata.normalize('NFD', song['title'].lower()).encode('ascii', 'ignore').decode())
        if len(t.split()) >= 2:
            best, bi = 0, None
            for i, b in enumerate(blocks):
                if b['label']: continue
                k = b['lyr'].count(t)
                if k > best: best, bi = k, i
            if bi is not None:
                chorus_group = 'T'; group[bi] = 'T'; ref_src = 'título na letra'
    if chorus_group is not None:
        for i, b in enumerate(blocks):
            if group.get(i) == chorus_group and (not b['label'] or b['label'] == 'Refrão'):
                b['label'] = 'Refrão'; b['src'] = b['src'] or ref_src
    ref_idx = [i for i, b in enumerate(blocks) if b['label'] == 'Refrão']
    ref_lines = ' '.join(blocks[i]['lyr'] for i in ref_idx)
    # 3) demais blocos por progressao
    rest = [i for i, b in enumerate(blocks) if not b['label']]  # (blocos com cifra)
    pgroups = []
    for i in rest:
        for g in pgroups:
            if sim(blocks[i]['deg'], blocks[g[0]]['deg']) >= 0.7:
                g.append(i); break
        else:
            pgroups.append([i])
    first_ref = ref_idx[0] if ref_idx else None
    verse_g = pgroups[0] if pgroups else []
    letters = 'ABCDEFGH'
    for gi, g in enumerate(pgroups):
        for i in g:
            b = blocks[i]
            followed_ref = (i + 1 in ref_idx)
            if g is verse_g and (len(g) >= 2 or ref_idx or n >= 3):
                b['label'] = 'Verso'; b['src'] = 'progressão repetida' if len(g) > 1 else 'posição'
            elif ref_idx and all((k + 1) in ref_idx for k in g) and i != 0:
                b['label'] = 'Pré-refrão'; b['src'] = 'antes do refrão'
            elif ref_idx and i > ref_idx[-1] and len(g) == 1:
                partial = any(l['t'] in ('pair', 'lyric') and len(block_lyric({'lines': [l]})) > 6
                              and block_lyric({'lines': [l]}) in ref_lines for l in b['lines'])
                b['label'] = 'Final' if partial else 'Ponte'; b['src'] = 'após último refrão'
            elif ref_idx and first_ref is not None and i > first_ref and len(g) == 1:
                b['label'] = 'Ponte'; b['src'] = 'trecho único'
            else:
                b['label'] = 'Parte ' + letters[min(gi, 7)]; b['src'] = 'progressão'
    # 4) numeracao
    seen = Counter()
    total = Counter(b['label'] for b in blocks)
    for b in blocks:
        seen[b['label']] += 1
        b['name'] = b['label'] + (f" {seen[b['label']]}" if total[b['label']] > 1 and b['label'] in ('Verso', 'Refrão', 'Pré-refrão') else '')


def analyze(song):
    allc = [c for b in song['blocks'] for c in block_chords(b)]
    if not allc: return None
    cand = detect_key(allc, song['meta'].get('tom'))
    sc, tonic, mode = cand[0]
    tname = tonic_spelling(tonic, mode, allc)
    scale = spell_scale(tname, mode)
    capo = song['meta'].get('capo', 0)
    degs_of = lambda b: [degree_label(c, tonic, mode) for c in block_chords(b)]
    label_blocks(song, degs_of)
    margin = cand[0][0] - cand[1][0]
    capo_src = 'cifra' if capo else None
    dec = parse_declared(song['meta'].get('tom'))
    if not capo and dec and dec != (tonic, mode):
        d = (dec[0] - tonic) % 12
        if dec[1] == mode and 1 <= d <= 7: capo, capo_src = d, 'inferido'
    sound = (tonic + capo) % 12
    sound_name = note_name(sound, key_uses_flats(sound, mode))
    # Se a relativa empata, informa
    alts = [{'tonic': tonic_spelling(t, m, allc), 'tonic_pc': t, 'mode': m, 'score': round(s, 1)} for s, t, m in cand[1:3]]
    out_blocks = []
    for b in song['blocks']:
        lines = []
        for l in b['lines']:
            if l['t'] == 'pair':
                lyr = l['lyric']
                cl = sorted(l['chords'], key=lambda x: x[1])
                # reconstruir de forma simples: cada acorde recebe o texto ate o proximo
                segs = []
                pos_list = [min(p, len(lyr)) for _, p in cl]
                if pos_list and pos_list[0] > 0: segs.append([None, lyr[:pos_list[0]]])
                for k, (c, _) in enumerate(cl):
                    st = pos_list[k]; en = pos_list[k + 1] if k + 1 < len(cl) else len(lyr)
                    segs.append([c, lyr[st:en]])
                lines.append({'t': 'pair', 'segs': [[cj(s[0], tonic, mode) if s[0] else None, s[1]] for s in segs]})
            elif l['t'] == 'chords':
                lines.append({'t': 'chords', 'chords': [cj(c, tonic, mode) for c in l['chords']]})
            else:
                lines.append({'t': 'lyric', 'lyric': l['lyric']})
        seq = b['deg']
        cyc = find_cycle(compress(seq)) if len(seq) >= 4 else None
        out_blocks.append({'name': b['name'], 'kind': b['label'], 'src': b['src'],
                           'pattern': compress(seq)[:24], 'cycle': cyc, 'lines': lines})
    structure = [b['name'] for b in out_blocks]
    used = []
    for c in allc:
        d = degree_label(c, tonic, mode)
        if d not in [u['deg'] for u in used]:
            used.append({'deg': d, 'chord': c['n'], 'in_key': diatonic_status(c, tonic, mode)})
    return {
        'title': song['title'], 'artist': song['artist'],
        'declared_key': song['meta'].get('tom'), 'capo': capo,
        'capo_src': capo_src,
        'key': {'tonic': tname, 'tonic_pc': tonic, 'mode': mode, 'sound_pc': sound, 'sound': sound_name, 'scale': scale,
                'score': round(sc, 1), 'margin': round(margin, 1), 'alts': alts},
        'structure': structure, 'chords_used': used, 'sections': out_blocks}


def cj(c, tonic, mode):
    return {'n': c['n'], 'r': c['r'], 'q': c['q'], 's': c['s'], 'b': c['b'],
            'deg': degree_label(c, tonic, mode), 'in': diatonic_status(c, tonic, mode)}


# ----------------------------------------------------------------- leitores
def read_docx_songbook(path):
    import docx
    d = docx.Document(path)
    songs, cur = [], None
    ps = d.paragraphs
    prev_title = False
    for p in ps:
        t = p.text.replace('\xa0', ' ')
        sizes = [r.font.size.pt for r in p.runs if r.text.strip() and r.font.size]
        is_title = bool(t.strip()) and bool(sizes) and all(s >= 18 for s in sizes)
        if is_title:
            title = t.strip().replace('\n', ' ')
            if prev_title and cur is not None and not cur['artist']:
                cur['artist'] = title; prev_title = False; continue
            m = re.match(r"^(.*?\S)\s{3,}(\S.*)$", title)
            cur = {'title': m.group(1) if m else title, 'artist': m.group(2) if m else '', 'lines': []}
            songs.append(cur); prev_title = True
            continue
        prev_title = False
        if cur is None: continue
        if t == '': cur['lines'].append('')
        else: cur['lines'].extend(t.split('\n'))
    # artista = primeira linha de texto sem acorde logo apos o titulo
    for s in songs:
        if not s['artist']:
            for i, ln in enumerate(s['lines']):
                if not ln.strip(): continue
                k, _ = classify(ln)
                if k == 'lyric' and len(ln) < 50:
                    s['artist'] = ln.strip(); s['lines'] = s['lines'][:i] + s['lines'][i + 1:]
                break
    return songs


def read_docx_plain(path):
    import docx
    d = docx.Document(path)
    lines = []
    for p in d.paragraphs:
        t = p.text.replace('\xa0', ' ')
        lines.extend(t.split('\n') if t else [''])
    return lines


def read_pdf(path):
    """Devolve lista de musicas. Titulos = linhas com fonte bem maior que o corpo."""
    import pdfplumber
    from statistics import median
    rows = []          # (texto_da_linha, eh_titulo)
    with pdfplumber.open(path) as pdf:
        for pg in pdf.pages:
            words = pg.extract_words(extra_attrs=['size'], keep_blank_chars=False, use_text_flow=False)
            if not words: continue
            body = median(w['size'] for w in words)
            cw = median((w['x1'] - w['x0']) / max(1, len(w['text'])) for w in words if w['size'] <= body * 1.1)
            lines = {}
            for w in words:
                lines.setdefault(round(w['top'] / 3), []).append(w)
            last = None
            tops = sorted(min(w['top'] for w in lines[k]) for k in lines)
            gaps = [b - a for a, b in zip(tops, tops[1:]) if b - a > 1]
            pitch = median(gaps) if gaps else body * 1.2
            for key in sorted(lines):
                ws = sorted(lines[key], key=lambda w: w['x0'])
                txt, col = '', 0
                for w in ws:
                    c = int(round((w['x0'] - pg.bbox[0]) / cw))
                    if c > len(txt): txt += ' ' * (c - len(txt))
                    elif txt and not txt.endswith(' '): txt += ' '
                    txt += w['text']
                big = max(w['size'] for w in ws) >= body * 1.35
                top = ws[0]['top']
                if last is not None:
                    for _ in range(max(0, int(round((top - last) / pitch)) - 1)): rows.append(('', False))
                if big: txt = re.sub(r"\s+", ' ', txt.strip())
                rows.append((txt.rstrip(), big)); last = top
            rows.append(('', False))
    songs, cur = [], None
    for txt, big in rows:
        if big:
            if cur is not None and not cur['lines'] and not cur['artist']:
                cur['artist'] = txt.strip(); continue
            cur = {'title': txt.strip(), 'artist': '', 'lines': []}; songs.append(cur); continue
        if cur is None: cur = {'title': os.path.splitext(os.path.basename(path))[0], 'artist': '', 'lines': []}; songs.append(cur)
        cur['lines'].append(txt)
    for s_ in songs:
        if not s_['artist']:
            for i, ln in enumerate(s_['lines']):
                if not ln.strip(): continue
                if classify(ln)[0] == 'lyric' and len(ln) < 50:
                    s_['artist'] = ln.strip(); s_['lines'] = s_['lines'][:i] + s_['lines'][i + 1:]
                break
    return songs


def read_image(path):
    import pytesseract
    from PIL import Image, ImageOps
    im = Image.open(path).convert('L')
    if im.width < 1600:
        f = 1600 / im.width
        im = im.resize((int(im.width * f), int(im.height * f)), Image.LANCZOS)
    im = ImageOps.autocontrast(im)
    cfg = '--oem 1 --psm 6 -c preserve_interword_spaces=1'
    try:
        txt = pytesseract.image_to_string(im, lang=os.environ.get('OCR_LANG', 'por'), config=cfg)
    except pytesseract.TesseractError:
        txt = pytesseract.image_to_string(im, config=cfg)
    return [clean_ocr_line(l) for l in txt.split('\n')]


def clean_ocr_line(l):
    """OCR costuma ler 'C' como 'Cc'. Se a linha vira so acordes depois da correcao, usa a corrigida."""
    def fix(t):
        return t[0] if re.fullmatch(r"[A-G][A-Ga-g]", t) and t[0].lower() == t[1].lower() else t
    toks = l.split()
    if toks and all(parse_chord(strip_tok(fix(t))) or t.lower() in MARKERS for t in toks):
        out = ''
        for m in re.finditer(r"\S+", l):
            out += ' ' * max(0, m.start() - len(out)) + fix(m.group())
        return out
    return l


def read_url(url):
    import requests, html as H
    r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
    r.raise_for_status()
    h = r.text
    title = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
    artist = re.search(r"<h2[^>]*>(.*?)</h2>", h, re.S)
    pre = re.search(r"<pre[^>]*>(.*?)</pre>", h, re.S)
    if not pre: raise SystemExit('Nao achei a cifra (<pre>) nessa pagina.')
    body = re.sub(r"<br\s*/?>", "\n", pre.group(1))
    body = re.sub(r"<[^>]+>", "", body)
    body = H.unescape(body)
    meta = []
    tom = re.search(r'id="cifra_tom"[^>]*>(.*?)</', h, re.S)
    capo = re.search(r'id="cifra_capo"[^>]*>(.*?)</', h, re.S)
    for m, pref in ((tom, 'Tom: '), (capo, 'Capotraste ')):
        if m:
            t = re.sub(r"<[^>]+>", " ", m.group(1)); t = H.unescape(t)
            t = re.sub(r"\s+", " ", t).strip()
            t = re.sub(r"^(tom|capotraste)\s*:?\s*", '', t, flags=re.I)
            if t: meta.append(pref + t)
    clean = lambda x: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", H.unescape(x))).strip() if x else ''
    return {'title': clean(title.group(1) if title else ''), 'artist': clean(artist.group(1) if artist else ''),
            'lines': meta + [''] + body.split('\n')}


def songs_from_lines(lines, base='Música'):
    title, artist, rest = base, '', lines
    nz = [i for i, l in enumerate(lines) if l.strip()][:2]
    if len(nz) == 2 and all(classify(lines[i])[0] == 'lyric' for i in nz) and nz[1] - nz[0] <= 2 and len(lines[nz[0]]) < 60 and len(lines[nz[1]]) < 60:
        title, artist = lines[nz[0]].strip(), lines[nz[1]].strip(); rest = lines[nz[1] + 1:]
    return {'title': title, 'artist': artist, 'lines': rest}


def songs_from_text(text, base='Música'):
    return [songs_from_lines(text.replace('\r', '').split('\n'), base)]


def analyze_songs(songs):
    res = []
    for s in songs:
        r = analyze(parse_song_lines(s['lines'], s['title'], s['artist']))
        if r: res.append(r)
    return res


def load_inputs(paths):
    songs = []
    for p in paths:
        if re.match(r"https?://", p):
            songs.append(read_url(p)); continue
        ext = os.path.splitext(p)[1].lower()
        base = os.path.splitext(os.path.basename(p))[0]
        if ext == '.docx':
            sb = read_docx_songbook(p)
            if len(sb) >= 2: songs.extend(sb); continue
            lines = read_docx_plain(p)
        elif ext == '.pdf':
            songs.extend(read_pdf(p)); continue
        elif ext in ('.png', '.jpg', '.jpeg', '.webp', '.bmp'): lines = read_image(p)
        else: lines = open(p, encoding='utf-8', errors='replace').read().split('\n')
        songs.append(songs_from_lines(lines, base))
    return songs


def to_markdown(res):
    md = []
    for s in res:
        k = s['key']
        md.append(f"## {s['title']} — {s['artist']}")
        capo = f" · capotraste {s['capo']}ª casa" if s['capo'] else ''
        md.append(f"**Tom:** {k['tonic']}{'m' if k['mode']=='m' else ''} ({'menor' if k['mode']=='m' else 'maior'}){capo} · escala: {' '.join(k['scale'])}")
        md.append(f"**Estrutura:** {' → '.join(s['structure'])}\n")
        for sec in s['sections']:
            pat = ' – '.join(sec['pattern'])
            cyc = f"  (ciclo: {' – '.join(sec['cycle'])})" if sec['cycle'] else ''
            md.append(f"- **{sec['name']}** [{sec['src']}]: {pat}{cyc}")
        md.append('')
    return '\n'.join(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('entradas', nargs='+')
    ap.add_argument('-o', '--saida', default='padroes')
    a = ap.parse_args()
    res = []
    for s in load_inputs(a.entradas):
        song = parse_song_lines(s['lines'], s['title'], s['artist'])
        r = analyze(song)
        if r: res.append(r)
        else: print('sem acordes:', s['title'], file=sys.stderr)
    json.dump(res, open(a.saida + '.json', 'w', encoding='utf-8'), ensure_ascii=False)
    open(a.saida + '.md', 'w', encoding='utf-8').write(to_markdown(res))
    print(f"{len(res)} musica(s) -> {a.saida}.json / {a.saida}.md")


if __name__ == '__main__':
    main()
