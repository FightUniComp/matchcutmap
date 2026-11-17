"""Auteur Atlas build script.

Reads the JSON files in data/, computes how similar every pair of profiled
directors is, lays them out in 2D so that distance means similarity, and writes
a single self-contained page to site/index.html.

Usage:  python build.py            (add --report to print a sanity check)
Needs:  numpy, scikit-learn
"""
import json, math, sys, os, re, statistics, unicodedata, difflib
import numpy as np
from sklearn.manifold import smacof

HERE = os.path.dirname(os.path.abspath(__file__))
def load(name, optional=False):
    p = os.path.join(HERE, "data", name + ".json")
    if optional and not os.path.exists(p): return None
    return json.load(open(p, encoding="utf-8"))

# How much each ingredient counts toward similarity. Movements are deliberately heavy.
W_TECHNIQUES, W_SCORES, W_MOVEMENTS = 0.42, 0.23, 0.35
# A historical movement counts fully; a looser critical category counts less.
KIND_WEIGHT = {"movement": 1.0, "category": 0.6}
W, H, PAD = 5200, 3600, 220
KEY_FILMS = 6
ERAS = [(1929, "Silent era, to 1929"), (1959, "1930 to 1959"), (1979, "1960 to 1979"), (1999, "1980 to 1999"), (9999, "2000 onward")]

T, MV, DIMS, D, I = load("techniques"), load("movements"), load("dimensions"), load("directors"), load("influence")
TSPDT, F, FILMS, DIRECTORY, SOURCES = load("tspdt"), load("facts"), load("films"), load("directory"), load("sources")
CANNES = load("cannes")   # winners of the top prize at Cannes, 1939 to 2026
BOOK = load("book", optional=True) or {"pages": {}, "pairs": {}}      # page references from the Oxford History of World Cinema
TMDB = load("tmdb", optional=True) or {"films": {}}    # written by scripts/fetch_tmdb.py
PEOPLE = load("people", optional=True) or {"directors": {}}   # filmographies and birth dates, also from scripts/fetch_tmdb.py
TID = {fid: m["tmdb_id"] for fid, m in TMDB["films"].items()}
def pyear(s): return int(s[:4]) if s and s[:4].isdigit() else None
WD = load("wikidata", optional=True) or {"directors": {}, "people": {}}     # written by scripts/fetch_wikidata.py (CC0)
def wd_people(i): return [WD["people"][p["qid"]] | {"qid": p["qid"]} for p in WD["directors"].get(i, []) if p["qid"] in WD["people"]]
REGIONS = {"North America": ["USA", "Canada"], "Latin America and the Caribbean": ["Mexico", "Brazil", "Argentina", "Chile", "Colombia", "Cuba", "Haiti"],
           "Western Europe": ["France", "UK", "Italy", "Germany", "Spain", "Portugal", "Belgium", "Netherlands", "Austria", "Switzerland", "Greece", "Sweden",
                              "Denmark", "Finland", "Norway", "Iceland", "Ireland"],
           "Central and Eastern Europe": ["Poland", "Czechoslovakia", "Hungary", "Romania", "Yugoslavia", "Soviet Union", "Russia", "Ukraine", "Georgia", "Armenia"],
           "East Asia": ["Japan", "China", "Hong Kong", "Taiwan", "South Korea"], "South and Southeast Asia": ["India", "Philippines", "Thailand", "Cambodia"],
           "Middle East and Africa": ["Iran", "Turkey", "Israel", "Egypt", "Lebanon", "Palestine", "Tunisia", "Algeria", "Senegal", "Mali", "Mauritania", "Chad", "Ethiopia", "Angola"],
           "Oceania": ["Australia", "New Zealand"]}
REGION_OF = {c: r for r, cs in REGIONS.items() for c in cs}
def first_country(d): return d["country"].split("/")[0].strip()
MAJOR = re.compile(r"palme d.or|golden lion|silver lion|golden bear|silver bear|cam[ée]ra d.or|cannes film festival grand prix|grand jury prize|(?<!special )jury prize"
                   r"|golden leopard|golden shell|praemium imperiale|grand prix des am[ée]riques"
                   r"|^academy award for best (director|picture|original screenplay|adapted screenplay|writing|animated feature|documentary feature|international feature|foreign language)"
                   r"|academy honorary award|honorary academy award|european film academy honorary award|european film academy lifetime achievement", re.I)
MAJOR_DIRECTING = re.compile(r"best direct", re.I)
MAJOR_BODY = re.compile(r"^academy award|cannes|berlin|venice|bafta|c[ée]sar|european film", re.I)
def tkey(t): return "".join(c for c in unicodedata.normalize("NFD", (t or "").lower()) if c.isalnum() and ord(c) < 128)
def pfilms(i):
    """TMDB filmography minus the films we already hold (same TMDB id, or same title within a year)."""
    ours = by_dir.get(i, [])
    have = {TID.get(f["id"]) for f in ours} - {None}
    seen = {(tkey(f["title"]), f["year"]) for f in ours}
    def dup(p):
        y = pyear(p.get("release_date"))
        return p["tmdb_id"] in have or any(t in (tkey(p.get("title")), tkey(p.get("original_title"))) and y and fy and abs(y - fy) <= 1 for t, fy in seen)
    return [p for p in PEOPLE["directors"].get(i, {}).get("films", []) if not dup(p)]

# ---------- validate ----------
ids = [d["id"] for d in D]
IDSET0 = set(ids)
IDSET = set(ids)
assert len(set(ids)) == len(ids), "duplicate director id"
keys = [m["key"] for m in DIMS]
for d in D:
    for t in d["techniques"]:
        assert t in T, f"{d['id']}: unknown technique {t}"
    assert len(set(d["techniques"])) == len(d["techniques"]), f"{d['id']}: duplicate technique"
    for m in d["movements"]:
        assert m in MV, f"{d['id']}: unknown movement {m}"
    assert all(1 <= d["scores"][k] <= 10 for k in keys), f"{d['id']}: score missing or out of range"
for e in I:
    assert e["from"] in ids and e["to"] in ids, e
assert len({(e["from"], e["to"]) for e in I}) == len(I), "duplicate influence link"
for k in F:
    assert k in ids, f"facts.json: unknown director {k}"
n = len(D)

# ---------- films per director ----------
def film_order(f):
    if f["tspdt"]: return f["tspdt"]
    if f.get("cannes"): return min(1100, 1000 + (f["sight_and_sound"] or 999))
    if f["sight_and_sound"]: return 1000 + f["sight_and_sound"]
    if f["house_of_tabula"]: return 3000
    return 5000
def film_out(f):
    o = {"t": f["title"]}
    if f["year"]: o["y"] = f["year"]
    if f["tspdt"]: o["ts"] = f["tspdt"]
    if f["sight_and_sound"]: o["ss"] = f["sight_and_sound"]
    if f["house_of_tabula"]: o["ht"] = 1
    if f.get("cannes"): o["ca"] = [f["cannes"]["year"], f["cannes"]["award"]]
    tm = TMDB["films"].get(f["id"])
    hk = ("m", tm["tmdb_id"]) if tm and tm.get("tmdb_id") else ("f", f["id"])
    if HON_FILM.get(hk): o["hn"] = HON_FILM[hk]
    if tm:
        for a, b in (("overview", "ov"), ("tmdb_id", "tid"), ("imdb_id", "im")):
            if tm.get(a): o[b] = tm[a]
        if tm.get("matched_title") and tkey(tm["matched_title"]) != tkey(f["title"]): o["tt"] = tm["matched_title"]
        if rate(tm): o["r"], o["rv"] = rate(tm), tm["vote_count"]
    return o
def rate(t):
    """TMDB audience rating, shown only when at least 20 people rated the film."""
    return round(t["vote_average"], 1) if (t.get("vote_count") or 0) >= 20 and t.get("vote_average") else None
by_dir = {}
for f in sorted(FILMS, key=film_order):
    for i in f["directors"]:
        by_dir.setdefault(i, []).append(f)
def plural(k, word): return f"{k} {word}" + ("" if k == 1 else "s")
def list_facts(i):
    fl = by_dir.get(i, [])
    out = []
    won = sorted([f for f in fl if f.get("cannes")], key=lambda f: f["cannes"]["year"])
    if won:
        def one(f):
            y = f["cannes"]["year"]
            other = [g["title"] for g in FILMS if g.get("cannes") and g["cannes"]["year"] == y and g["id"] != f["id"]]
            return f"{f['title']} ({y}" + (", shared" if other else "") + ")"
        names = {f["cannes"]["award"] for f in won}
        prize = "the Palme d'Or" if names == {"Palme d'Or"} else "the top prize at Cannes"
        out.append(f"Won {prize}" + (" twice" if len(won) == 2 else "") + (": " if len(won) > 1 else " for ") + " and ".join(one(f) for f in won) + ".")
    ts = [f for f in fl if f["tspdt"]]
    if ts:
        out.append(f"{plural(len(ts), 'film')} in the TSPDT 1,000 Greatest Films; the highest is {ts[0]['title']} at #{ts[0]['tspdt']}.")
    ss = sorted([f for f in fl if f["sight_and_sound"]], key=lambda f: f["sight_and_sound"])
    if ss:
        top = [f for f in ss if f["sight_and_sound"] <= 100]
        s = f"{plural(len(ss), 'film')} received votes in the 2022 Sight and Sound critics' poll"
        s += f", {len(top)} of them in the top 100" if len(top) > 1 else ""
        out.append(s + f"; the highest is {ss[0]['title']} at #{ss[0]['sight_and_sound']}.")
    ht = [f["title"] for f in fl if f["house_of_tabula"]]
    if ht:
        out.append("On the House of Tabula film studies watchlist: " + ", ".join(ht[:4]) + (f" and {len(ht) - 4} more" if len(ht) > 4 else "") + ".")
    out += honour_lines(i)
    pg = BOOK["pages"].get(i, [])
    if pg:
        out.append(f"Named on {plural(len(pg), 'page')} of The Oxford History of World Cinema.")
    return out
def period_span(text):
    """'1958 to late 1960s' -> [1958, 1969]; '1990s onward' -> [1990, this year]; None for a coined term."""
    if "term" in text: return None
    toks = re.findall(r"(early|mid|late)?\s*(\d{4})(s?)", text)
    if not toks: return None
    def rng(q, y, dec):
        y = int(y)
        if not dec: return y, y
        return {"early": (y, y + 3), "mid": (y + 3, y + 6), "late": (y + 6, y + 9)}.get(q, (y, y + 9))
    a, b = rng(*toks[0])[0], rng(*toks[-1])[1]
    return [a, NOW_YEAR if "onward" in text else b]
NOW_YEAR = 2026
def main_years(i):
    """Years of the films that define a career: TMDB films with some audience, else our own film list."""
    ys = [pyear(p.get("release_date")) for p in PEOPLE["directors"].get(i, {}).get("films", []) if (p.get("vote_count") or 0) >= 10]
    ys = [y for y in ys if y]
    return ys if len(ys) >= 3 else [f["year"] for f in by_dir.get(i, []) if f["year"]]
def era_of(d):
    ys = main_years(d["id"])
    y = statistics.median(ys) if ys else (d["born"] + 40 if d.get("born") else 1960)
    return next(k for k, (lim, _) in enumerate(ERAS) if y <= lim)
def span(i):
    ys = main_years(i)
    return [min(ys), max(ys)] if ys else None

# ---------- similarity ----------
def weighted_cosine(vocab, member, weight):
    df = {v: sum(1 for d in D if v in member(d)) for v in vocab}
    w = np.array([weight(v) * math.log((n + 1) / (df[v] + 0.5)) for v in vocab])
    M = np.array([[w[j] if v in member(d) else 0.0 for j, v in enumerate(vocab)] for d in D])
    norm = np.linalg.norm(M, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return (M / norm) @ (M / norm).T

tech_sim = weighted_cosine(list(T), lambda d: d["techniques"], lambda v: 1.0)
mov_sim = weighted_cosine(list(MV), lambda d: d["movements"], lambda v: KIND_WEIGHT[MV[v]["kind"]])
sc = np.array([[d["scores"][k] for k in keys] for d in D], dtype=float)
score_sim = 1 - np.abs(sc[:, None, :] - sc[None, :, :]).mean(axis=2) / 9.0
S = W_TECHNIQUES * tech_sim + W_SCORES * score_sim + W_MOVEMENTS * mov_sim
np.fill_diagonal(S, 1.0)
dist = 1 - S
np.fill_diagonal(dist, 0.0)

# ---------- layout ----------
best = None
for seed in range(6):
    X, stress = smacof(dist, n_components=2, n_init=1, random_state=seed, max_iter=400)
    if best is None or stress < best[1]:
        best = (X, stress)
X = best[0]
X = X - X.min(axis=0)
X = X / X.max(axis=0)
X[:, 0] = PAD + X[:, 0] * (W - 2 * PAD)
X[:, 1] = PAD + X[:, 1] * (H - 2 * PAD)

# Each director is grouped under the first listed movement that has "cluster": true.
primary = {}
for i, d in enumerate(D):
    for m in d["movements"]:
        if MV[m]["cluster"]:
            primary.setdefault(m, []).append(i)
            break
groups = {m: np.array(mem) for m, mem in primary.items() if len(mem) >= 2}
radius = {m: 66 * math.sqrt(len(mem)) + 20 for m, mem in groups.items()}

out_deg = {i: 0 for i in ids}
for e in I:
    out_deg[e["from"]] += 1
R = np.array([11 + 5.5 * math.sqrt(out_deg[i]) for i in ids])

def separate_nodes():
    """push overlapping circles and labels apart (labels sit under the circles, so more room vertically)"""
    dx = X[None, :, 0] - X[:, None, 0]
    dy = (X[None, :, 1] - X[:, None, 1]) * 1.6
    dd = np.sqrt(dx * dx + dy * dy)
    np.fill_diagonal(dd, 1e9)
    need = R[:, None] + R[None, :] + 54
    over = np.clip(need - dd, 0, None)
    if not (over > 0.5).any():
        return False
    dd = np.maximum(dd, 0.01)
    X[:, 0] -= (dx / dd * over / 2).sum(axis=1) * 0.6
    X[:, 1] -= (dy / dd * over / 2 / 1.6).sum(axis=1) * 0.6
    return True

gl = list(groups)
for _ in range(260):
    cen = {m: X[groups[m]].mean(axis=0) for m in gl}
    for m in gl:   # keep each movement compact
        v = X[groups[m]] - cen[m]
        dd = np.linalg.norm(v, axis=1)
        far = dd > radius[m]
        if far.any():
            X[groups[m][far]] = cen[m] + v[far] * ((radius[m] + (dd[far] - radius[m]) * 0.7) / dd[far])[:, None]
    for ai in range(len(gl)):   # keep movements apart from each other
        for bi in range(ai + 1, len(gl)):
            ma, mb = gl[ai], gl[bi]
            v = X[groups[mb]].mean(axis=0) - X[groups[ma]].mean(axis=0)
            dd = np.linalg.norm(v) or 0.01
            need = radius[ma] + radius[mb] + 100
            if dd < need:
                sh = v / dd * (need - dd) / 2 * 0.5
                X[groups[ma]] -= sh
                X[groups[mb]] += sh
    cen = {m: X[groups[m]].mean(axis=0) for m in gl}
    for m in gl:   # keep outsiders out of a movement's area
        v = X - cen[m]
        dd = np.maximum(np.linalg.norm(v, axis=1), 0.01)
        inside = dd < radius[m] + 60
        inside[groups[m]] = False
        if inside.any():
            X[inside] += v[inside] / dd[inside][:, None] * ((radius[m] + 60 - dd[inside]) * 0.5)[:, None]
    separate_nodes()
    X[:, 0] = np.clip(X[:, 0], PAD, W - PAD)
    X[:, 1] = np.clip(X[:, 1], PAD + 60, H - PAD)
for _ in range(300):
    if not separate_nodes():
        break

# ---------- neighbours and links ----------
near, style = {}, {}
for a in range(n):
    order = [b for b in np.argsort(-S[a]) if b != a][:4]
    near[ids[a]] = []
    for rank, b in enumerate(order):
        shared = [t for t in D[a]["techniques"] if t in D[b]["techniques"]]
        smov = [m for m in D[a]["movements"] if m in D[b]["movements"]]
        near[ids[a]].append({"id": ids[b], "sim": round(float(S[a, b]), 2), "shared": shared, "mov": smov})
        if rank < 2 and (shared or smov):
            style[tuple(sorted((ids[a], ids[b])))] = round(float(S[a, b]), 2)

ranks = TSPDT["ranks"]
def tier(i):
    r, o = ranks.get(i, 999), out_deg[i]
    return 1 if (r <= 30 or o >= 9) else 2 if (r <= 110 or o >= 3) else 3

def pfilm_out(p):
    o = {"t": p["title"], "tid": p["tmdb_id"]}
    if pyear(p.get("release_date")): o["y"] = pyear(p["release_date"])
    if rate(p): o["r"], o["rv"] = rate(p), p["vote_count"]
    if p.get("overview"): o["ov"] = p["overview"]
    if HON_FILM.get(("m", p["tmdb_id"])): o["hn"] = HON_FILM[("m", p["tmdb_id"])]
    return o
def key_films(i):
    """Films on the lists first, by rank; then the rest of the career by TMDB audience size."""
    fl = by_dir.get(i, [])
    ranked = [f for f in fl if film_order(f) < 5000]
    hk = lambda f: ("m", (TMDB["films"].get(f["id"]) or {}).get("tmdb_id")) if (TMDB["films"].get(f["id"]) or {}).get("tmdb_id") else ("f", f["id"])
    pool = [(1 if honoured(hk(f)) else 0, (TMDB["films"].get(f["id"]) or {}).get("vote_count") or 0, film_out(f)) for f in fl if film_order(f) >= 5000]
    pool += [(1 if honoured(("m", p["tmdb_id"])) else 0, p.get("vote_count") or 0, pfilm_out(p)) for p in pfilms(i) if pyear(p.get("release_date"))]
    pool.sort(key=lambda x: (-x[0], -x[1]))
    pool = [(v, o) for _, v, o in pool]
    return ([film_out(f) for f in ranked] + [o for _, o in pool])[:KEY_FILMS]
def filmography(i):
    if not PEOPLE["directors"].get(i, {}).get("films"): return None
    out = [[pyear(p.get("release_date")), p["title"], p["tmdb_id"], rate(p)] for p in pfilms(i) if pyear(p.get("release_date"))]
    out += [[f["year"], f["title"], TID.get(f["id"]), rate(TMDB["films"].get(f["id"]) or {})] for f in by_dir.get(i, []) if f["year"]]
    for x in out:
        h = HON_FILM.get(("m", x[2])) if x[2] else None
        x.append("; ".join(b for _, b in h) if h else None)
    def trim(x):
        while x and x[-1] is None and len(x) > 3: x = x[:-1]
        return x
    return [trim(x) for x in sorted(out, key=lambda x: (x[0], x[1]))]

# ---------- lists and awards: Oscars and Cahiers du cinéma, plus the lists above, resolved to directors and films ----------
OSC, CAH = load("oscars"), load("cahiers")
SPECIAL = str.maketrans({"ł": "l", "ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "đ": "d", "ð": "d", "þ": "th", "ı": "i"})
def nfold(s): return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower().translate(SPECIAL)) if c.isalnum() and ord(c) < 128)
NAME_ALIAS = {"howard hawkes": "Howard Hawks", "joseph mankiewitz": "Joseph L. Mankiewicz", "abel ganc": "Abel Gance", "joseph von sternberg": "Josef von Sternberg",
    "coen brothers": "Joel and Ethan Coen", "joel coen": "Joel and Ethan Coen", "ethan coen": "Joel and Ethan Coen", "straub–huillet": "Jean-Marie Straub & Danièle Huillet",
    "jean-marie straub": "Jean-Marie Straub & Danièle Huillet", "danièle huillet": "Jean-Marie Straub & Danièle Huillet", "sam fuller": "Samuel Fuller",
    "michaelangelo antonioni": "Michelangelo Antonioni", "ben safdie": "Josh & Benny Safdie", "josh safdie": "Josh & Benny Safdie", "benny safdie": "Josh & Benny Safdie",
    "joshua safdie": "Josh & Benny Safdie", "ernst shoedsack": "Merian C. Cooper & Ernest B. Schoedsack", "merian j. cooper": "Merian C. Cooper & Ernest B. Schoedsack",
    "daniel kwan": "Daniels", "daniel scheinert": "Daniels", "stanley donen": "Stanley Donen & Gene Kelly", "gene kelly": "Stanley Donen & Gene Kelly", "yuliya solntseva": "Alexander Dovzhenko"}
NAME_BY = {}
for d in D:
    for nm in [d["name"]] + d.get("members", []) + d.get("aka", []): NAME_BY.setdefault(nfold(nm), d["id"])
NAME_FULL = [(d["id"], nm) for d in D for nm in [d["name"]] + d.get("members", []) + d.get("aka", [])]
def nparts(n): return [x for x in re.split(r"[\s.]+", unicodedata.normalize("NFC", n)) if x]
def find_director(name):
    """A name as a list spells it -> the id of a director on the map, or None."""
    name = NAME_ALIAS.get(name.lower(), name)
    if nfold(name) in NAME_BY: return NAME_BY[nfold(name)]
    w = nparts(name)
    if len(w) < 2: return None
    last, first = nfold(w[-1]), [nfold(x) for x in w[:-1]]
    for i, other in NAME_FULL:
        v = nparts(other)
        if len(v) < 2: continue
        l2, f2 = nfold(v[-1]), [nfold(x) for x in v[:-1]]
        if not first[0] or not f2[0]: continue
        if l2 != last and difflib.SequenceMatcher(None, l2, last).ratio() < 0.86: continue
        same = first[0] == f2[0] or (len(first[0]) > 3 and difflib.SequenceMatcher(None, first[0], f2[0]).ratio() >= 0.7)
        initials = first[0][0] == f2[0][0] and (len(first[0]) == 1 or len(f2[0]) == 1)
        if same or initials: return i
    return None
def split_names(names):
    ps = [x.strip() for x in re.split(r"\s*&\s*|\s+and\s+(?=[A-Z])|,\s+(?=[A-Z])", " & ".join(names)) if x.strip()]
    if len(ps) > 1 and len(ps[-1].split()) >= 2: ps = [x if len(x.split()) > 1 else x + " " + ps[-1].split()[-1] for x in ps]
    return ps
def dirs_of(names): return list(dict.fromkeys(i for i in (find_director(n) for n in split_names(names)) if i))
ARTICLE = re.compile(r"^(the|a|an|le|la|les|l'|il|lo|el|der|die|das)\s+", re.I)
def tvars(t):
    """'The Mirror' -> mirror, themirror; 'Cries & Whispers' -> criesandwhispers, crieswhispers"""
    if not t: return set()
    vs = {t, t.replace("&", "and"), ARTICLE.sub("", t), ARTICLE.sub("", t.replace("&", "and"))}
    return {k for k in (nfold(v) for v in vs) if k}
def title_keys(*titles):
    out = []
    for t in titles:
        if not t: continue
        out.append(t)
        m = re.match(r"^(.*?)\s*\((.+)\)$", t)
        if m: out += [m.group(1), m.group(2)]
    return list(dict.fromkeys(k for x in out for k in tvars(x)))
CANDS = {}
def film_cands(i):
    if i not in CANDS:
        out = []
        for f in by_dir.get(i, []):
            tm = TMDB["films"].get(f["id"]) or {}
            out.append((("m", tm["tmdb_id"]) if tm.get("tmdb_id") else ("f", f["id"]), tvars(f["title"]) | tvars(tm.get("matched_title")), f["year"], tm.get("vote_count") or 0))
        for p in PEOPLE["directors"].get(i, {}).get("films", []):
            out.append((("m", p["tmdb_id"]), tvars(p.get("title")) | tvars(p.get("original_title")), pyear(p.get("release_date")), p.get("vote_count") or 0))
        CANDS[i] = out
    return CANDS[i]
def match_film(dids, titles, year=None):
    """The film a list entry means, among the films of its directors: ('m', TMDB id) or ('f', our id)."""
    want, best = title_keys(*titles), None
    for i in dids:
        for key, ts, y, votes in film_cands(i):
            if any(w in ts for w in want): sc = 2
            elif any(len(w) >= 5 and any(len(t) >= 5 and (t.startswith(w) or w.startswith(t)) for t in ts) for w in want): sc = 1
            else: continue
            dy = abs(y - year) if year and y else 0
            if sc == 1 and year and dy > (15 if min(len(w) for w in want) >= 12 else 3): continue
            c = (sc, -dy, votes)
            if best is None or c > best[0]: best = (c, key)
    return best[1] if best else None
def fkey_js(k): return "m%d" % k[1] if k and k[0] == "m" else ""
LISTS, HON_FILM, HON_DIR = {}, {}, {}
def new_list(key, group, name, short, kind, src, url, note=""):
    LISTS[key] = {"group": group, "name": name, "short": short, "kind": kind, "src": src, "url": url, "note": note, "e": []}
def entry(key, label, title, year, dids, names, fk, badge=None, line=None):
    LISTS[key]["e"].append([label, title, year, dids, names, fkey_js(fk)])
    if badge and fk: HON_FILM.setdefault(fk, []).append([key, badge])
    if line:
        for i in dids: HON_DIR.setdefault(i, {}).setdefault(key, []).append(line)
NICE = {"picture": ("oscar-picture", "Oscar: Best Picture", "Oscar for Best Picture"), "director": ("oscar-director", "Oscar: Best Director", "Oscar for Best Director"),
        "international": ("oscar-international", "Oscar: International Feature", "Oscar for Best International Feature Film")}
for cat in ("picture", "director", "international"):
    key, badge, name = NICE[cat]
    new_list(key, "Awards", name, badge.replace("Oscar: ", "Oscar, "), "award", "Academy Awards", "https://awardsdatabase.oscars.org",
             "Best Foreign Language Film until 2019; an honorary award until 1955." if cat == "international" else ("Two awards in the first year, for dramatic and comedy direction." if cat == "director" else ""))
    for e in OSC[cat]:
        dids = dirs_of(e["directors"]); fk = match_film(dids, [e["film"], e.get("original")], e["year"])
        b = ("Honorary Oscar, foreign-language film" if e.get("honorary") else badge)
        entry(key, e["label"], e["film"], e["year"], dids, " and ".join(split_names(e["directors"])), fk, b, [e["film"], e["label"]])
new_list("cannes", "Awards", "Top prize at Cannes", "Cannes top prize", "award", "Festival de Cannes", SOURCES["cannes"]["url"] if "cannes" in SOURCES else "")
FBY = {f["id"]: f for f in FILMS}
for c in CANNES:
    f = FBY.get(c["film"]); tm = TMDB["films"].get(c["film"]) or {}
    entry("cannes", str(c["year"]), f["title"] if f else c["film"], c["year"], [i for i in c["directors"] if i in IDSET0], " and ".join(next((d["name"] for d in D if d["id"] == i), i) for i in c["directors"]),
          ("m", tm["tmdb_id"]) if tm.get("tmdb_id") else None)
C100 = CAH["top100"]
new_list("cahiers-100", "Critics' lists", "Cahiers du cinéma: 100 films for an ideal cinémathèque", "Cahiers 100", "ranked", "Cahiers du cinéma, 2008",
         "https://blog.matthewhunt.com/2008/11/100-films-pour-une-cinematheque-ideale.html", f"Voted by {C100['voters']} French critics and historians in {C100['year']}; films with the same number of votes share a rank.")
for e in C100["films"]:
    dids = dirs_of(e["directors"]); fk = match_film(dids, [e["film"], e.get("original")])
    r = "%d%s" % (e["rank"], "=" if e["tied"] else "")
    entry("cahiers-100", r, e["film"], None, dids, " and ".join(split_names(e["directors"])), fk, "Cahiers 100: #" + r, [e["film"], "#" + r])
new_list("cahiers-annual", "Critics' lists", "Cahiers du cinéma: top 10 of the year", "Cahiers top 10", "yearly", "Cahiers du cinéma, 1951 to 2025",
         "https://en.wikipedia.org/wiki/Cahiers_du_Cin%C3%A9ma%27s_Annual_Top_10_Lists", "The magazine's critics' list of the year's best films, as published in France; no lists for 1952, 1953, 1969 to 1980 and 2003.")
for e in CAH["annual"]:
    dids = dirs_of(e["directors"]); fk = match_film(dids, [e["film"], e.get("original")], e["year"])
    r = e["rank"] or 0
    entry("cahiers-annual", str(e["year"]), e["film"], e["year"], dids, " and ".join(split_names(e["directors"])), fk, "Cahiers top 10, %d: #%d" % (e["year"], r), [e["film"], e["year"], r])
    LISTS["cahiers-annual"]["e"][-1].append(r)
new_list("cahiers-decades", "Critics' lists", "Cahiers du cinéma: best of the decade", "Cahiers decade", "yearly", "Cahiers du cinéma", "https://en.wikipedia.org/wiki/Cahiers_du_Cin%C3%A9ma%27s_Annual_Top_10_Lists",
         "Ten films each for the 1990s, 2000s and 2010s.")
for e in CAH["decades"]:
    dids = dirs_of(e["directors"]); fk = match_film(dids, [e["film"], e.get("original")])
    entry("cahiers-decades", "%ds" % e["year"], e["film"], None, dids, " and ".join(split_names(e["directors"])), fk, "Cahiers best of the %ds: #%d" % (e["year"], e["rank"] or 0), [e["film"], e["year"], e["rank"] or 0])
    LISTS["cahiers-decades"]["e"][-1].append(e["rank"] or 0)
def fk_of(f):
    tm = TMDB["films"].get(f["id"]) or {}
    return ("m", tm["tmdb_id"]) if tm.get("tmdb_id") else None
def names_of(f): return " and ".join(next((d["name"] for d in D if d["id"] == i), i) for i in f["directors"])
new_list("tspdt-films", "Critics' lists", "They Shoot Pictures: the 1,000 greatest films", "TSPDT 1,000", "ranked", "They Shoot Pictures, Don't They?, 2026", TSPDT["url"])
for f in sorted([f for f in FILMS if f["tspdt"]], key=lambda f: f["tspdt"]): entry("tspdt-films", str(f["tspdt"]), f["title"], f["year"], [i for i in f["directors"] if i in IDSET0], names_of(f), fk_of(f))
new_list("tspdt-directors", "Critics' lists", "They Shoot Pictures: the 250 greatest directors", "TSPDT 250", "people", "They Shoot Pictures, Don't They?, 2026", TSPDT["url"])
for i, r in sorted(TSPDT["ranks"].items(), key=lambda x: x[1]):
    if i in IDSET0: entry("tspdt-directors", str(r), next(d["name"] for d in D if d["id"] == i), None, [i], "", None)
new_list("sight-and-sound", "Critics' lists", "Sight and Sound: greatest films of all time", "Sight and Sound", "ranked", "Sight and Sound critics' poll, 2022", SOURCES["sight_and_sound"]["url"])
for f in sorted([f for f in FILMS if f["sight_and_sound"] and f["sight_and_sound"] <= 250], key=lambda f: f["sight_and_sound"]):
    entry("sight-and-sound", str(f["sight_and_sound"]), f["title"], f["year"], [i for i in f["directors"] if i in IDSET0], names_of(f), fk_of(f))
new_list("house-of-tabula", "Critics' lists", "The House of Tabula: film studies watchlist", "House of Tabula", "ranked", "The House of Tabula", "")
for f in sorted([f for f in FILMS if f["house_of_tabula"]], key=lambda f: f["house_of_tabula"]):
    entry("house-of-tabula", str(f["house_of_tabula"]), f["title"], f["year"], [i for i in f["directors"] if i in IDSET0], names_of(f), fk_of(f))
ICE = load("iceberg")
new_list("tabula-iceberg", "Critics' lists", "The House of Tabula: cinematic complexity iceberg", "Tabula iceberg", "grouped", "The House of Tabula", SOURCES.get("tabula_iceberg", {}).get("url", ""),
         "68 films in eight tiers, from the accessible to the abyss, as listed by an IMDb user from the channel's video.")
for e in ICE["films"]:
    dids = dirs_of(e["directors"]); fk = match_film(dids, [e["film"]], e["year"])
    entry("tabula-iceberg", "Tier %d: %s" % (e["tier"], e["tier_name"]), e["film"] + (" (%s)" % e["note"] if e.get("note") else ""), e["year"], dids,
          " and ".join(split_names(e["directors"])), fk, "Tabula iceberg: tier %d" % e["tier"], [e["film"], e["tier"]])
    LISTS["tabula-iceberg"]["e"][-1].append(e["n"])
for L in LISTS.values():
    L["n"] = len(L["e"]); L["onmap"] = sum(1 for x in L["e"] if x[3])
def honour_lines(i):
    """Lines for 'On the lists' from the Oscars and Cahiers lists."""
    H, out = HON_DIR.get(i, {}), []
    def films(xs): return ", ".join(f"{t} ({y})" for t, y in xs)
    for key, word in (("oscar-director", "the Oscar for Best Director"), ("oscar-picture", "Best Picture with"), ("oscar-international", "the Oscar for international feature with")):
        xs = H.get(key)
        if not xs: continue
        if key == "oscar-director": out.append(f"Won {word}" + (f" {len(xs)} times: " if len(xs) > 1 else " for ") + films(xs) + ".")
        elif key == "oscar-picture": out.append(f"Won {word} " + films(xs) + ".")
        else: out.append(f"Won {word} " + films(xs) + ".")
    xs = H.get("cahiers-100")
    if xs: out.append(f"{plural(len(xs), 'film')} in Cahiers du cinéma's 100 films for an ideal cinémathèque (2008): " + ", ".join(f"{t} ({r})" for t, r in xs) + ".")
    xs = H.get("cahiers-annual")
    if xs:
        ones = [x for x in xs if x[2] == 1]
        out.append(f"{plural(len(xs), 'film')} in Cahiers du cinéma's top 10 of the year, {min(x[1] for x in xs)} to {max(x[1] for x in xs)}" + (f"; {len(ones)} of them the year's #1" if len(ones) > 1 else f"; {ones[0][0]} was #1 in {ones[0][1]}" if ones else "") + ".")
    xs = H.get("tabula-iceberg")
    if xs: out.append("On The House of Tabula's cinematic complexity iceberg: " + ", ".join(f"{t} (tier {r})" for t, r in xs) + ".")
    xs = H.get("cahiers-decades")
    if xs: out.append("In Cahiers du cinéma's best of the decade: " + ", ".join(f"{t} (#{r} of the {y}s)" for t, y, r in xs) + ".")
    return out
TOP_HON = {"oscar-picture", "oscar-director", "oscar-international", "cahiers-100", "cahiers-decades", "tabula-iceberg"}
def honoured(fk): return any(k in TOP_HON or (k == "cahiers-annual" and b.endswith(": #1")) for k, b in HON_FILM.get(fk, []))
def life(i):
    ps = PEOPLE["directors"].get(i, {}).get("persons", [])
    out = [[p["name"], pyear(p.get("birthday")), pyear(p.get("deathday")), (p.get("place_of_birth") or "").split(",")[0].strip()] for p in ps]
    w = wd_people(i)
    if len(w) == 1 and len(out) <= 1 and pyear(w[0].get("birth")):      # one person: Wikidata dates and birthplace win
        nm = out[0][0] if out else w[0]["label"]
        out = [[nm, pyear(w[0].get("birth")), pyear(w[0].get("death")), w[0].get("birthplace") or (out[0][3] if out else "")]]
    return out or None
def awards(i):
    seen, out = set(), []
    for p in wd_people(i):
        for a in p.get("awards", []):
            lab = a.get("award") or ""
            if not (MAJOR.search(lab) or (MAJOR_DIRECTING.search(lab) and MAJOR_BODY.search(lab))): continue
            key = (lab, a.get("year"), a.get("work"))
            if key in seen: continue
            seen.add(key); out.append([lab, int(a["year"]) if a.get("year") else None, a.get("work")])
    return sorted(out, key=lambda x: (x[1] or 9999, x[0]))
Q2D = {p["qid"]: did for did, ps in WD["directors"].items() for p in ps}
REL_NAME = {"P22": "Father", "P25": "Mother", "P40": "Child", "P26": "Spouse", "P3373": "Sibling"}
def family(i):
    out = []
    for p in wd_people(i):
        for r in p.get("rel", []):
            o = Q2D.get(r["qid"])
            if r["p"] in REL_NAME and o and o != i and [REL_NAME[r["p"]], o] not in out: out.append([REL_NAME[r["p"]], o])
    return out
def beyond(i):
    """influences that Wikidata records from outside this map: writers, painters, other filmmakers"""
    out, seen = [], set()
    for p in wd_people(i):
        for r in p.get("rel", []):
            if r["p"] == "P737" and r["qid"] not in Q2D and r.get("label") and not re.fullmatch(r"Q\d+", r["label"]) and r["qid"] not in seen:
                seen.add(r["qid"]); out.append([r["label"], r["qid"]])
    return out
ROLE_ORDER = ["Cinematography", "Editing", "Music", "Writing", "Production design", "Acting"]
def collab(i):
    c = PEOPLE["directors"].get(i, {}).get("collab") or []
    return [[role, [[x["name"], len(x["films"]), x["tmdb_id"]] for x in sorted([x for x in c if x["role"] == role], key=lambda x: -len(x["films"]))[:4]]]
            for role in ROLE_ORDER if any(x["role"] == role for x in c)]
SHARED = {}
for _did, _v in PEOPLE["directors"].items():
    for _c in _v.get("collab") or []: SHARED.setdefault((_c["role"], _c["tmdb_id"]), set()).add(_did)
def shared(i):
    out = {}
    for c in PEOPLE["directors"].get(i, {}).get("collab") or []:
        for o in SHARED.get((c["role"], c["tmdb_id"]), ()):
            if o != i and o in IDSET: out.setdefault(o, []).append([c["role"], c["name"]])
    return sorted([[o, v] for o, v in out.items()], key=lambda x: -len(x[1]))[:8]
def director_out(i, d):
    fl = by_dir.get(d["id"], [])
    fx = F.get(d["id"], {})
    o = {"id": d["id"], "name": d["name"], "country": d["country"], "movements": d["movements"],
         "films": key_films(d["id"]), "nfilms": len(filmography(d["id"]) or fl), "span": span(d["id"]), "rank": ranks.get(d["id"]),
         "sig": fx.get("signature", ""), "desc": fx.get("description", ""), "facts": [[f["text"], 1 if f["status"] == "verified" else 0] for f in fx.get("facts", [])], "lists": list_facts(d["id"]),
         "tags": d["techniques"], "dims": [d["scores"][k] for k in keys],
         "x": round(float(X[i, 0]), 1), "y": round(float(X[i, 1]), 1), "r": round(float(R[i]), 1), "tx": TL[i][0], "ty": TL[i][1], "tr": TL[i][2],
         "out": out_deg[d["id"]], "era": era_of(d), "tier": tier(d["id"]), "near": near[d["id"]]}
    if d.get("born"): o["born"] = d["born"]
    fg, lf = filmography(d["id"]), life(d["id"])
    if fg: o["fg"] = fg
    if lf: o["life"] = lf
    o["region"] = REGION_OF.get(first_country(d), "Other")
    w = wd_people(d["id"])
    if len(w) == 1 and w[0].get("enwiki"): o["wiki"] = w[0]["enwiki"]
    for k, fn in (("awards", awards), ("family", family), ("beyond", beyond), ("collab", collab), ("shared", shared)):
        v = fn(d["id"])
        if v: o[k] = v
    return o

# ---------- timeline: x = middle of the career, one lane per region, packed as a beeswarm ----------
LANES = [r for r in ["North America", "Latin America and the Caribbean", "Western Europe", "Central and Eastern Europe", "Middle East and Africa",
                     "South and Southeast Asia", "East Asia", "Oceania", "Other"] if any(REGION_OF.get(first_country(d), "Other") == r for d in D)]
TY0, TY1, TX0, TX1, TM = 1890, 2030, 780, W - 140, 150
def tl_x(year): return TX0 + (year - TY0) / (TY1 - TY0) * (TX1 - TX0)
lane_n = {r: sum(1 for d in D if REGION_OF.get(first_country(d), "Other") == r) for r in LANES}
lane_w = {r: (lane_n[r] + 25) ** 0.85 for r in LANES}
TL_LANES, _y = [], TM
for r in LANES:
    h = (H - 2 * TM) * lane_w[r] / sum(lane_w.values()); TL_LANES.append([r, round(_y, 1), round(_y + h, 1)]); _y += h
TL = {}
for r, y0, y1 in TL_LANES:
    members = sorted([i for i, d in enumerate(D) if REGION_OF.get(first_country(d), "Other") == r], key=lambda i: -R[i])
    placed = []                                              # (x, y, radius)
    for i in members:
        ys = main_years(D[i]["id"]); yr = statistics.median(ys) if ys else 1960
        x, rad, cy = tl_x(min(TY1, max(TY0, yr))), 0.62 * R[i] + 2, (y0 + y1) / 2
        best_y, best_pen = cy, None
        for k in range(0, 400):
            y = cy + (k + 1) // 2 * 6 * (1 if k % 2 else -1)
            if y - rad < y0 + 6 or y + rad > y1 - 6:
                if k > 40 and best_pen is not None: break
                continue
            pen = sum(max(0, rad + pr + 3 - math.hypot(x - px, y - py)) for px, py, pr in placed if abs(px - x) < rad + pr + 3)
            if best_pen is None or pen < best_pen: best_y, best_pen = y, pen
            if pen == 0: break
        placed.append((x, best_y, rad)); TL[i] = (round(x, 1), round(best_y, 1), round(rad, 1))

# ---------- pairs of directors who share a collaborator (crew layer; not actors) ----------
CREW = {}
for (_role, _pid), _ds in SHARED.items():
    if _role == "Acting": continue
    _ds = sorted(x for x in _ds if x in IDSET)
    for _a in range(len(_ds)):
        for _b in range(_a + 1, len(_ds)): CREW[(_ds[_a], _ds[_b])] = CREW.get((_ds[_a], _ds[_b]), 0) + 1

def evidence(e):
    return BOOK["pairs"].get(e["from"] + "|" + e["to"]) or BOOK["pairs"].get(e["to"] + "|" + e["from"]) or []

data = {
 "w": W, "h": H, "eras": [lab for _, lab in ERAS], "sources": SOURCES, "timeline": {"lanes": TL_LANES, "years": [[y, round(tl_x(y), 1)] for y in range(1900, 2030, 10)], "x0": TX0, "x1": TX1, "y0": TY0, "y1": TY1},
 "crew": [[a, b, n] for (a, b), n in sorted(CREW.items())],
 "hasTmdb": bool(TMDB["films"]), "hasPeople": bool(PEOPLE["directors"]), "hasWikidata": bool(WD["people"]),
 "regions": {r: sorted({first_country(d) for d in D if REGION_OF.get(first_country(d)) == r}) for r in list(REGIONS) + ["Other"] if any(REGION_OF.get(first_country(d), "Other") == r for d in D)},
 "counts": {"films": len(FILMS), "tspdt": sum(1 for f in FILMS if f["tspdt"]), "ss": sum(1 for f in FILMS if f["sight_and_sound"]), "hot": sum(1 for f in FILMS if f["house_of_tabula"]), "cannes": len(CANNES), "factsChecked": sum(1 for v in F.values() for f in v.get("facts", []) if f["status"] == "verified"), "facts": sum(len(v.get("facts", [])) for v in F.values()),
            "notes": sum(1 for e in I if e["note"]), "evidence": sum(1 for e in I if evidence(e))},
 "rankSource": {"name": TSPDT["source"], "edition": TSPDT["edition"], "url": TSPDT["url"]},
 "techniques": {k: {"name": v["name"], "cat": v["category"], "def": v["definition"]} for k, v in T.items()},
 "movements": {k: {"name": v["name"], "kind": v["kind"], "period": v["period"], "span": period_span(v["period"]), "desc": v["description"],
                   "members": [d["id"] for d in D if k in d["movements"]],
                   "primary": [ids[i] for i in groups.get(k, [])]} for k, v in MV.items()},
 "dims": [{"key": m["key"], "lo": m["low"], "hi": m["high"]} for m in DIMS],
 "lists": LISTS,
 "directors": [director_out(i, d) for i, d in enumerate(D)],
 "directory": [{"id": e["id"], "name": e["name"], "films": [film_out(f) for f in by_dir.get(e["id"], [])[:KEY_FILMS]]} for e in DIRECTORY],
 "influence": [dict({"s": e["from"], "t": e["to"], "note": e["note"]}, **({"ev": evidence(e)[:3]} if evidence(e) else {}), **({"wd": 1} if "wikidata" in e.get("sources", []) else {})) for e in I],
 "style": [{"a": a, "b": b, "sim": v} for (a, b), v in style.items()],
}

if "--report" in sys.argv:
    name = {d["id"]: d["name"] for d in D}
    print(n, "directors,", len(DIRECTORY), "directory-only,", len(T), "techniques,", len(MV), "movements,", len(I), "influence links,", len(style), "style links,", len(FILMS), "films")
    for k in ["ozu", "ford", "bresson", "scorsese", "ernstlubitsch", "johncarpenter", "stanbrakhage", "frederickwiseman", "hayaomiyazaki", "ridleyscott", "nicolasroeg", "pedrocosta"]:
        print(f"{name[k]:22s}", ", ".join(f"{name[x['id']]} {x['sim']}" for x in near[k]))
    print("unused techniques:", [t for t in T if not any(t in d["techniques"] for d in D)], "| used once:", [t for t in T if sum(t in d["techniques"] for d in D) == 1])
    print("movements without members:", [m for m in MV if not any(m in d["movements"] for d in D)])
    print("era counts:", [sum(1 for d in data["directors"] if d["era"] == k) for k in range(len(ERAS))], "| tiers:", [sum(1 for d in data["directors"] if d["tier"] == k) for k in (1, 2, 3)])
    print("clusters:", {m: len(v) for m, v in groups.items()})

import base64
def data_uri(path):
    return "data:image/png;base64," + base64.b64encode(open(os.path.join(HERE, path), "rb").read()).decode()
tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
assert "__DATA__" in tpl
tpl = tpl.replace("__LOGO__", data_uri("assets/logo-light.png")).replace("__FAVICON__", data_uri("assets/favicon.png"))
os.makedirs(os.path.join(HERE, "site"), exist_ok=True)
out = os.path.join(HERE, "site", "index.html")
open(out, "w", encoding="utf-8").write(tpl.replace("__DATA__", json.dumps(data, ensure_ascii=False, separators=(",", ":"))))
print("wrote", out, os.path.getsize(out) // 1024, "KB")
os.makedirs(os.path.join(HERE, "docs"), exist_ok=True)   # GitHub Pages serves this folder
open(os.path.join(HERE, "docs", "index.html"), "w", encoding="utf-8").write(open(out, encoding="utf-8").read())
