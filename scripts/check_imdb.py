"""Check our film data against your own copy of the IMDb datasets.

    python scripts/check_imdb.py PATH/title.basics.tsv PATH/title.crew.tsv

Download the two files from https://datasets.imdbws.com (non-commercial use only).
The script only reads them to find problems in our data: TMDB matches that point
to the wrong film, years that are far off, and films whose director credit does not
fit the rest of that director's films. It writes a local report, imdb_report.json,
which must not be committed: IMDb's licence does not allow republishing its data.
"""
import collections, csv, difflib, json, os, sys, unicodedata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(n): return json.load(open(os.path.join(HERE, "data", n + ".json"), encoding="utf-8"))
def fold(s): return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if c.isalnum() and ord(c) < 128)

if len(sys.argv) < 3: sys.exit(__doc__)
films = {f["id"]: f for f in load("films")}
names = {d["id"]: d["name"] for d in load("directors")}
tm = load("tmdb")["films"]
want = {m["imdb_id"]: fid for fid, m in tm.items() if m.get("imdb_id") and fid in films}

def rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        for line in fh:
            p = line.rstrip("\n").rstrip("\r").split("\t")
            if p[0] in want: yield p
basics = {p[0]: p for p in rows(sys.argv[1])}          # tconst type primary original adult start end runtime genres
crew = {p[0]: [x for x in p[1].split(",") if x != "\\N"] for p in rows(sys.argv[2])}

issues = []
def flag(kind, fid, **kw): issues.append(dict(kind=kind, film=fid, title=films[fid]["title"], year=films[fid]["year"], directors=[names.get(d, d) for d in films[fid]["directors"]], **kw))

OK_TYPES = {"movie", "tvMovie", "short", "tvShort", "tvMiniSeries", "tvSeries", "video", "tvSpecial"}
for tc, fid in want.items():
    b = basics.get(tc)
    if not b: flag("not in IMDb file", fid, imdb=tc); continue
    f = films[fid]
    sim = max(difflib.SequenceMatcher(None, fold(f["title"]), fold(t)).ratio() for t in (b[2], b[3]))
    inside = any(fold(f["title"])[:12] in fold(t) or fold(t)[:12] in fold(f["title"]) for t in (b[2], b[3]) if fold(t))
    y = int(b[5]) if b[5].isdigit() else None
    if b[1] not in OK_TYPES: flag("wrong kind of title", fid, imdb=tc, imdb_type=b[1], imdb_title=b[2])
    if sim < 0.5 and not inside and (not y or not f["year"] or abs(y - f["year"]) > 1):
        flag("title and year differ", fid, imdb=tc, imdb_title=b[2], imdb_original=b[3], imdb_year=y)
    elif y and f["year"] and abs(y - f["year"]) >= 2:
        flag("year differs by 2 or more", fid, imdb=tc, imdb_title=b[2], imdb_year=y)

# one IMDb person per director (several for teams), then films that do not fit
by_dir = collections.defaultdict(list)
for tc, fid in want.items():
    for d in films[fid]["directors"]: by_dir[d].append((fid, crew.get(tc, [])))
for d, lst in by_dir.items():
    if len(lst) < 2: continue
    c = collections.Counter(n for _, ns in lst for n in set(ns))
    top = [n for n, k in c.items() if k >= max(2, 0.5 * len(lst))]
    if not top:
        issues.append(dict(kind="director has no common IMDb person", director=names.get(d, d), films=[films[f]["title"] for f, _ in lst]))
        continue
    for fid, ns in lst:
        if ns and not set(ns) & set(top):
            flag("director credit does not fit", fid, director=names.get(d, d), imdb_directors=ns, usual=top)

out = os.path.join(HERE, "imdb_report.json")
json.dump(issues, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(len(want), "films checked,", len(issues), "issues ->", out)
for k, n in collections.Counter(i["kind"] for i in issues).most_common(): print(f"  {n:4d}  {k}")
