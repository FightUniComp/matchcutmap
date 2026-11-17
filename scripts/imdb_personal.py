"""Make a private file of IMDb ratings for the films on the map, for your own use.

    python scripts/imdb_personal.py RATINGS [BASICS CREW]

RATINGS, BASICS and CREW are your own downloads of title.ratings.tsv, title.basics.tsv
and title.crew.tsv from https://datasets.imdbws.com. IMDb allows personal, non-commercial
use of these files and does not allow republishing them, so IMDb ratings never go on the
website. This script writes personal/imdb-ratings.json instead. On auteuratlas.org, press
Import under "Your films" and choose that file: the ratings then show on the film cards,
in your browser only.

With only the ratings file it covers the films we matched on TMDB, through their IMDb ids.
Add the basics and crew files to cover each director's whole filmography as well (this
needs data/people.json from fetch_tmdb.py). Keep the output to yourself: it is IMDb data.
"""
import datetime, json, os, sys, unicodedata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(n, default):
    p = os.path.join(HERE, "data", n + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default
def fold(s):
    s = (s or "").lower()
    return "".join(c for c in unicodedata.normalize("NFD", s) if c.isalnum() and ord(c) < 128) or s.replace(" ", "")
def year(s):
    try: return int(str(s)[:4])
    except (TypeError, ValueError): return None
def tsv(path, ids):
    """The rows of an IMDb .tsv file whose first column is in ids (checked before splitting, for speed)."""
    with open(path, encoding="utf-8", newline="") as fh:
        next(fh)
        for line in fh:
            if line[:line.find("\t")] in ids: yield line.rstrip("\r\n").split("\t")

if len(sys.argv) not in (2, 4): sys.exit(__doc__)
films = {f["id"]: f for f in load("films", [])}
tm = load("tmdb", {}).get("films", {})
people = load("people", {}).get("directors", {})
want = {}                                       # IMDb title id -> page keys ("m" + TMDB id)
def add(tt, tid):
    if tt and tid: want.setdefault(tt, set()).add("m" + str(tid))
for fid, m in tm.items():
    if fid in films: add(m.get("imdb_id"), m.get("tmdb_id"))
print(f"{len(want)} films with an IMDb id from TMDB")

if len(sys.argv) == 4:
    if not people: sys.exit("data/people.json is missing: run scripts/fetch_tmdb.py first, or leave out BASICS and CREW.")
    nm = {}                                     # IMDb person id -> our director ids
    for i, rec in people.items():
        for p in rec.get("persons", []):
            if p.get("imdb_id"): nm.setdefault(p["imdb_id"], set()).add(i)
    made = {}                                   # director id -> IMDb title ids they directed
    with open(sys.argv[3], encoding="utf-8", newline="") as fh:   # title.crew: tconst, directors, writers
        next(fh)
        for line in fh:
            t, ds, _ = line.split("\t", 2)
            if ds != "\\N":
                for d in ds.split(","):
                    for i in nm.get(d, ()): made.setdefault(i, []).append(t)
    every = {t for ts in made.values() for t in ts}
    info = {p[0]: p for p in tsv(sys.argv[2], every)}   # tconst type primary original adult start ...
    rank = {"movie": 0, "tvMovie": 1, "video": 2, "short": 3}
    found = 0
    for i, ts in made.items():
        idx = {}
        for t in sorted(ts, key=lambda t: rank.get(info.get(t, [0, ""])[1], 9)):
            b = info.get(t)
            if not b or not year(b[5]): continue
            for title in (b[2], b[3]): idx.setdefault((fold(title), year(b[5])), t)
        todo = [(p.get("tmdb_id"), (p.get("title"), p.get("original_title")), year(p.get("release_date"))) for p in people[i].get("films", [])]
        todo += [((tm.get(f["id"]) or {}).get("tmdb_id"), (f["title"],), f.get("year")) for f in films.values() if i in f.get("directors", [])]
        for tid, titles, y in todo:
            if not tid or not y: continue
            hit = next((idx[(fold(t), y + dy)] for dy in (0, -1, 1) for t in titles if t and (fold(t), y + dy) in idx), None)
            if hit: add(hit, tid); found += 1
    print(f"{found} filmography entries matched through the director's IMDb credits")

out = {}
for p in tsv(sys.argv[1], want):
    for k in want[p[0]]: out[k] = [float(p[1]), int(p[2])]
os.makedirs(os.path.join(HERE, "personal"), exist_ok=True)
path = os.path.join(HERE, "personal", "imdb-ratings.json")
json.dump({"kind": "auteur-atlas/imdb-personal", "made": datetime.date.today().isoformat(),
           "notice": "IMDb ratings from IMDb's non-commercial datasets (https://developer.imdb.com/non-commercial-datasets/), for personal use only. Do not share or publish this file.",
           "ratings": out}, open(path, "w", encoding="utf-8"), separators=(",", ":"))
print(f"wrote {path}: IMDb ratings for {len(out)} films. Import it under 'Your films' on the site.")
