"""Build the Auteur Atlas database from the JSON files in data/.

    python scripts/build_db.py

Writes database/auteur-atlas.sqlite (one file, opens in DB Browser for SQLite,
https://sqlitebrowser.org) and one CSV per table in database/csv/.
The JSON files stay the source of truth: edit those, then rebuild.

Every claim that could be wrong carries a status:
  verified  checked against the source named in source_id
  draft     written from general film knowledge, not yet checked
"""
import csv, json, os, sqlite3, sys
# Public build (the default, committed to the repo): our own data plus TMDB and IMDb ids for linking.
# TMDB's terms allow showing its data with attribution but not redistributing it, so descriptions,
# ratings, birth dates and filmographies from TMDB go only into the local build:
#     python scripts/build_db.py --with-tmdb   ->  database/auteur-atlas-full.sqlite (not committed)
FULL = "--with-tmdb" in sys.argv
# IMDb ratings from your own download of title.ratings.tsv (https://datasets.imdbws.com). IMDb allows these files
# for personal, non-commercial use only and forbids republishing them, so they go only into the local full build:
#     python scripts/build_db.py --with-tmdb --imdb=path/to/title.ratings.tsv
IMDB = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--imdb=")), None)
if IMDB and not FULL: sys.exit("--imdb needs --with-tmdb: IMDb ratings are for personal use and never go into the public build.")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(name, optional=False):
    p = os.path.join(HERE, "data", name + ".json")
    if optional and not os.path.exists(p): return None
    return json.load(open(p, encoding="utf-8"))

D, F, FILMS, DIRECTORY = load("directors"), load("facts"), load("films"), load("directory")
T, MV, DIMS, I, SRC = load("techniques"), load("movements"), load("dimensions"), load("influence"), load("sources")
TSPDT, CANNES = load("tspdt")["ranks"], load("cannes")
BOOK = load("book", optional=True) or {"pages": {}, "pairs": {}}
TMDB = (load("tmdb", optional=True) or {"films": {}})["films"]
PEOPLE = (load("people", optional=True) or {"directors": {}})["directors"] if FULL else {}   # TMDB person records and filmographies
WDATA = load("wikidata", optional=True) or {"directors": {}, "people": {}}   # Wikidata is CC0, so it goes into the public build too
keys = [m["key"] for m in DIMS]

out_dir = os.path.join(HERE, "database")
csv_dir = os.path.join(out_dir, "csv-full" if FULL else "csv")
os.makedirs(csv_dir, exist_ok=True)
db_path = os.path.join(out_dir, "auteur-atlas-full.sqlite" if FULL else "auteur-atlas.sqlite")
if os.path.exists(db_path): os.remove(db_path)
db = sqlite3.connect(db_path)
db.executescript(f"""
CREATE TABLE sources (id TEXT PRIMARY KEY, name TEXT, detail TEXT, url TEXT, used_for TEXT);
CREATE TABLE directors (id TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT, born INTEGER, profiled INTEGER NOT NULL, tspdt_rank INTEGER,
  signature TEXT, description TEXT, text_status TEXT, {", ".join("score_" + k + " INTEGER" for k in keys)}, scores_status TEXT, book_pages INTEGER);
CREATE TABLE films (id TEXT PRIMARY KEY, title TEXT NOT NULL, year INTEGER, country TEXT, runtime INTEGER, colour TEXT, genre TEXT,
  tspdt_rank INTEGER, sight_and_sound_rank INTEGER, sight_and_sound_votes INTEGER, house_of_tabula_position INTEGER,
  tmdb_id INTEGER, imdb_id TEXT, tmdb_rating REAL, tmdb_votes INTEGER, overview TEXT, added_by_hand INTEGER);
CREATE TABLE director_people (director_id TEXT REFERENCES directors(id), name TEXT, tmdb_person_id INTEGER, imdb_person_id TEXT,
  birth_date TEXT, death_date TEXT, place_of_birth TEXT, found_by TEXT, source_id TEXT);
CREATE TABLE wikidata_people (director_id TEXT REFERENCES directors(id), qid TEXT, label TEXT, enwiki TEXT, birth_date TEXT, death_date TEXT,
  birthplace TEXT, citizenship TEXT, found_by TEXT);
CREATE TABLE wikidata_awards (director_id TEXT REFERENCES directors(id), qid TEXT, award TEXT, award_qid TEXT, year INTEGER, work TEXT, work_qid TEXT);
CREATE TABLE wikidata_relations (director_id TEXT REFERENCES directors(id), qid TEXT, property TEXT, relation TEXT, target_qid TEXT, target_label TEXT,
  target_director_id TEXT);
CREATE TABLE collaborators (director_id TEXT REFERENCES directors(id), tmdb_person_id INTEGER, name TEXT, role TEXT, films INTEGER, source_id TEXT);
CREATE TABLE filmography (director_id TEXT REFERENCES directors(id), tmdb_film_id INTEGER, title TEXT, original_title TEXT, release_date TEXT,
  tmdb_rating REAL, tmdb_votes INTEGER, source_id TEXT);
CREATE TABLE film_directors (film_id TEXT REFERENCES films(id), director_id TEXT REFERENCES directors(id), PRIMARY KEY (film_id, director_id));
CREATE TABLE awards (film_id TEXT REFERENCES films(id), festival TEXT, award TEXT, year INTEGER, source_id TEXT REFERENCES sources(id), status TEXT);
CREATE TABLE movements (id TEXT PRIMARY KEY, name TEXT, kind TEXT, period TEXT, description TEXT, has_map_area INTEGER);
CREATE TABLE director_movements (director_id TEXT REFERENCES directors(id), movement_id TEXT REFERENCES movements(id), position INTEGER, status TEXT);
CREATE TABLE techniques (id TEXT PRIMARY KEY, name TEXT, category TEXT, definition TEXT);
CREATE TABLE director_techniques (director_id TEXT REFERENCES directors(id), technique_id TEXT REFERENCES techniques(id), status TEXT);
CREATE TABLE style_scales (key TEXT PRIMARY KEY, low_label TEXT, high_label TEXT);
CREATE TABLE influences (from_id TEXT REFERENCES directors(id), to_id TEXT REFERENCES directors(id), note TEXT, status TEXT, source_id TEXT, book_scan_pages TEXT,
  PRIMARY KEY (from_id, to_id));
CREATE TABLE facts (id INTEGER PRIMARY KEY, director_id TEXT REFERENCES directors(id), text TEXT, status TEXT, source_id TEXT);
CREATE TABLE book_mentions (director_id TEXT REFERENCES directors(id), scan_page INTEGER);
CREATE TABLE list_entries (list TEXT, label TEXT, year INTEGER, rank INTEGER, tied INTEGER, votes INTEGER, film TEXT, original_title TEXT, directors TEXT, country TEXT, ceremony INTEGER, note TEXT);
CREATE VIEW to_verify AS
  SELECT 'fact' AS kind, d.name AS subject, f.text AS claim FROM facts f JOIN directors d ON d.id = f.director_id WHERE f.status = 'draft'
  UNION ALL SELECT 'influence', a.name || ' -> ' || b.name, i.note FROM influences i JOIN directors a ON a.id = i.from_id JOIN directors b ON b.id = i.to_id WHERE i.status = 'draft';
CREATE VIEW director_overview AS
  SELECT d.id, d.name, d.country, d.tspdt_rank,
    (SELECT COUNT(*) FROM film_directors fd WHERE fd.director_id = d.id) AS films_listed,
    (SELECT COUNT(*) FROM film_directors fd JOIN awards a ON a.film_id = fd.film_id WHERE fd.director_id = d.id) AS cannes_wins,
    (SELECT COUNT(*) FROM influences i WHERE i.from_id = d.id) AS influenced,
    (SELECT COUNT(*) FROM influences i WHERE i.to_id = d.id) AS influenced_by
  FROM directors d WHERE d.profiled = 1;
""")
db.executemany("INSERT INTO sources VALUES (?,?,?,?,?)", [(k, v["name"], v["detail"], v["url"], v["used_for"]) for k, v in SRC.items()])
OSC, CAH = load("oscars", optional=True), load("cahiers", optional=True)
rows = []
for cat in ("picture", "director", "international"):
    for e in (OSC or {}).get(cat, []):
        rows.append(("oscar-" + cat, e["label"], e["year"], None, None, None, e["film"], e.get("original") or None, " & ".join(e["directors"]), e.get("country"), e["ceremony"],
                     "honorary award" if e.get("honorary") else e.get("note")))
for e in (CAH or {}).get("top100", {}).get("films", []):
    rows.append(("cahiers-100", "%d%s" % (e["rank"], "=" if e["tied"] else ""), 2008, e["rank"], int(e["tied"]), e["votes"], e["film"], e.get("original") or None, " & ".join(e["directors"]), None, None, None))
for key, part in (("cahiers-annual", "annual"), ("cahiers-decades", "decades")):
    for e in (CAH or {}).get(part, []):
        rows.append((key, str(e["year"]) + ("s" if part == "decades" else ""), e["year"], e["rank"], None, None, e["film"], e.get("original") or None, " & ".join(e["directors"]), e.get("country") or None, None, None))
db.executemany("INSERT INTO list_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
for d in D:
    fx = F.get(d["id"], {})
    db.execute("INSERT INTO directors VALUES (" + ",".join("?" * (11 + len(keys))) + ")",
               [d["id"], d["name"], d["country"], d.get("born"), 1, TSPDT.get(d["id"]), fx.get("signature"), fx.get("description"), "draft"]
               + [d["scores"][k] for k in keys] + ["draft", len(BOOK["pages"].get(d["id"], []))])
    for n, m in enumerate(d["movements"]): db.execute("INSERT INTO director_movements VALUES (?,?,?,?)", (d["id"], m, n + 1, "draft"))
    for t in d["techniques"]: db.execute("INSERT INTO director_techniques VALUES (?,?,?)", (d["id"], t, "draft"))
    for f in fx.get("facts", []): db.execute("INSERT INTO facts (director_id, text, status, source_id) VALUES (?,?,?,?)", (d["id"], f["text"], f["status"], f["source"]))
    for p in BOOK["pages"].get(d["id"], []): db.execute("INSERT INTO book_mentions VALUES (?,?)", (d["id"], p))
for e in DIRECTORY:
    db.execute("INSERT INTO directors (id, name, profiled) VALUES (?,?,0)", (e["id"], e["name"]))
db.execute("INSERT INTO directors (id, name, profiled) VALUES ('x:directorsvarious', 'Various directors', 0)")   # anthology films such as Fantasia
known = {r[0] for r in db.execute("SELECT id FROM directors")}
for f in FILMS:
    tm = TMDB.get(f["id"], {})
    if not FULL: tm = {"tmdb_id": tm.get("tmdb_id"), "imdb_id": tm.get("imdb_id")}   # ids only in the public build
    db.execute("INSERT INTO films VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f["id"], f["title"], f["year"], f["country"], f["runtime"], f["colour"], f["genre"], f["tspdt"],
               f["sight_and_sound"], f["sight_and_sound_votes"], f["house_of_tabula"], tm.get("tmdb_id"), tm.get("imdb_id"), tm.get("vote_average"), tm.get("vote_count"), tm.get("overview"),
               1 if f.get("added") == "hand" else 0))
    for i in f["directors"]:
        assert i in known, (f["id"], i)
        db.execute("INSERT OR IGNORE INTO film_directors VALUES (?,?)", (f["id"], i))
if IMDB:
    want = {r[0] for r in db.execute("SELECT imdb_id FROM films WHERE imdb_id IS NOT NULL")}
    db.execute("CREATE TABLE imdb_ratings (imdb_id TEXT PRIMARY KEY, rating REAL, votes INTEGER)")
    with open(IMDB, encoding="utf-8") as fh:
        next(fh)
        db.executemany("INSERT INTO imdb_ratings VALUES (?,?,?)", [(a, float(b), int(c)) for a, b, c in (l.rstrip("\n").split("\t") for l in fh) if a in want])
for did, v in PEOPLE.items():
    if did not in known: continue
    for p in v.get("persons", []):
        db.execute("INSERT INTO director_people VALUES (?,?,?,?,?,?,?,?,?)", (did, p["name"], p["tmdb_id"], p.get("imdb_id"), p.get("birthday"), p.get("deathday"), p.get("place_of_birth"), v.get("how"), "tmdb"))
    for x in v.get("films", []):
        db.execute("INSERT INTO filmography VALUES (?,?,?,?,?,?,?,?)", (did, x["tmdb_id"], x["title"], x.get("original_title"), x.get("release_date"), x.get("vote_average"), x.get("vote_count"), "tmdb"))
    ps = v.get("persons", [])
    if len(ps) == 1 and (ps[0].get("birthday") or "")[:4].isdigit():
        db.execute("UPDATE directors SET born = ? WHERE id = ?", (int(ps[0]["birthday"][:4]), did))
q2d = {p["qid"]: did for did, ps in WDATA["directors"].items() for p in ps}
props = WDATA.get("properties", {})
for did, ps in WDATA["directors"].items():
    if did not in known: continue
    for p in ps:
        w = WDATA["people"].get(p["qid"])
        if not w: continue
        db.execute("INSERT INTO wikidata_people VALUES (?,?,?,?,?,?,?,?,?)", (did, p["qid"], w.get("label"), w.get("enwiki"), (w.get("birth") or "")[:10] or None,
                   (w.get("death") or "")[:10] or None, w.get("birthplace"), ", ".join(w.get("citizenship", [])), p.get("found_by")))
        for a in w.get("awards", []):
            db.execute("INSERT INTO wikidata_awards VALUES (?,?,?,?,?,?,?)", (did, p["qid"], a.get("award"), a.get("award_qid"), int(a["year"]) if str(a.get("year") or "").lstrip("-").isdigit() else None, a.get("work"), a.get("work_qid")))
        for r in w.get("rel", []):
            db.execute("INSERT INTO wikidata_relations VALUES (?,?,?,?,?,?,?)", (did, p["qid"], r["p"], props.get(r["p"]), r["qid"], r.get("label"), q2d.get(r["qid"])))
for did, v in PEOPLE.items():
    for c in v.get("collab") or []:
        if did in known: db.execute("INSERT INTO collaborators VALUES (?,?,?,?,?,?)", (did, c["tmdb_id"], c["name"], c["role"], len(c["films"]), "tmdb"))
for c in CANNES: db.execute("INSERT INTO awards VALUES (?,?,?,?,?,?)", (c["film"], "Cannes Film Festival", c["award"], c["year"], "cannes", "verified"))
db.executemany("INSERT INTO movements VALUES (?,?,?,?,?,?)", [(k, v["name"], v["kind"], v["period"], v["description"], int(v["cluster"])) for k, v in MV.items()])
db.executemany("INSERT INTO techniques VALUES (?,?,?,?)", [(k, v["name"], v["category"], v["definition"]) for k, v in T.items()])
db.executemany("INSERT INTO style_scales VALUES (?,?,?)", [(m["key"], m["low"], m["high"]) for m in DIMS])
for e in I:
    pages = BOOK["pairs"].get(e["from"] + "|" + e["to"]) or BOOK["pairs"].get(e["to"] + "|" + e["from"]) or []
    stated = "Oxford History of World Cinema" in e["note"]; wd = "wikidata" in e.get("sources", [])
    db.execute("INSERT INTO influences VALUES (?,?,?,?,?,?)", (e["from"], e["to"], e["note"], "verified" if (stated or wd) else "draft",
               "wikidata" if wd else ("ohwc" if (stated or pages) else None), ",".join(map(str, pages))))
db.commit()

counts = {}
for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') ORDER BY name").fetchall():
    cur = db.execute(f"SELECT * FROM {name}")
    rows = cur.fetchall(); counts[name] = len(rows)
    with open(os.path.join(csv_dir, name + ".csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh); w.writerow([c[0] for c in cur.description]); w.writerows(rows)
db.close()
print("wrote", db_path, os.path.getsize(db_path) // 1024, "KB")
for k, v in counts.items(): print(f"  {k:22s}{v:6d} rows")
