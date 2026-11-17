"""Fetch facts about our directors from Wikidata into data/wikidata.json.

    python scripts/fetch_wikidata.py

Wikidata is public domain (CC0), so unlike IMDb or TMDB data this file may be committed
and published. No key is needed. Run scripts/fetch_tmdb.py first: directors are found
through the IMDb and TMDB person ids in data/people.json, and by name otherwise.

Fetched per person: birth and death, birthplace, citizenship, English Wikipedia article,
awards with year and film, 'influenced by', teachers and students, movements, and family.
Afterwards run:  python scripts/merge_wikidata.py   and   python build.py
"""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"
UA = "AuteurAtlas/1.0 (https://auteuratlas.org; map of film directors)"

def load(name, default=None):
    p = os.path.join(HERE, "data", name + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

def sparql(query, tries=6):
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(SPARQL, data=body, headers={"User-Agent": UA, "Accept": "application/sparql-results+json",
                                                                     "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)["results"]["bindings"]
        except urllib.error.HTTPError as e:
            wait = int(e.headers.get("Retry-After") or 0) or 5 * (attempt + 1)
            print("  Wikidata answered HTTP %d, waiting %ds" % (e.code, wait)); time.sleep(wait)
        except Exception as e:
            print("  request failed (%s), retrying" % e); time.sleep(3 * (attempt + 1))
    sys.exit("Wikidata did not answer after several tries. Run the script again later; nothing was written.")

def api(**params):
    params.update(format="json")
    req = urllib.request.Request(API + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
        except Exception: time.sleep(2 * (attempt + 1))
    return {}

def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n): yield seq[i:i + n]
def qid(uri): return uri.rsplit("/", 1)[1]
def val(b, k): return b[k]["value"] if k in b else None

directors = load("directors"); people = (load("people", {}) or {}).get("directors", {})
# one entry per real person: team entries are split into their members
persons = []
for d in directors:
    ps = people.get(d["id"], {}).get("persons") or []
    if ps:
        for p in ps: persons.append({"dir": d["id"], "name": p["name"], "imdb": p.get("imdb_id"), "tmdb": p.get("tmdb_id")})
    else:
        for nm in d.get("members") or [d["name"]]: persons.append({"dir": d["id"], "name": nm, "imdb": None, "tmdb": None})
print(len(directors), "directors,", len(persons), "people to find on Wikidata")

# 1. find each person's Wikidata item: IMDb id first, then TMDB id, then a name search
def by_id(prop, values):
    found = {}
    for part in chunks(sorted(set(values)), 150):
        q = "SELECT ?item ?id WHERE { VALUES ?id { %s } ?item wdt:%s ?id . }" % (" ".join('"%s"' % v for v in part), prop)
        for b in sparql(q): found.setdefault(val(b, "id"), qid(val(b, "item")))
        time.sleep(1)
    return found
imdb = by_id("P345", [p["imdb"] for p in persons if p["imdb"]])
tmdb = by_id("P4985", [str(p["tmdb"]) for p in persons if p["tmdb"]])
for p in persons:
    p["qid"] = imdb.get(p["imdb"]) or tmdb.get(str(p["tmdb"])) if (p["imdb"] or p["tmdb"]) else None
    p["how"] = "id" if p["qid"] else None
WORDS = ("director", "filmmaker", "film maker", "animator", "screenwriter", "cinematographer", "documentar", "film", "artist", "choreographer")
for p in [p for p in persons if not p["qid"]]:
    res = api(action="wbsearchentities", search=p["name"], language="en", type="item", limit=7).get("search", [])
    hit = next((r for r in res if any(w in (r.get("description") or "").lower() for w in WORDS)), None)
    if hit: p["qid"], p["how"] = hit["id"], "name search"
    time.sleep(0.3)
found = [p for p in persons if p["qid"]]
print("found", len(found), "of", len(persons), "(%d by name search)" % sum(1 for p in found if p["how"] == "name search"))

# 2. facts about the found people, in batches
qids = sorted({p["qid"] for p in found})
info = {q: {"label": None, "enwiki": None, "birth": None, "death": None, "birthplace": None, "citizenship": [], "awards": [], "rel": []} for q in qids}
def batch(template, handle):
    for part in chunks(qids, 80):
        for b in sparql(template % " ".join("wd:" + q for q in part)): handle(b)
        time.sleep(1)
print("fetching birth, death and Wikipedia articles")
def basic(b):
    r = info[qid(val(b, "item"))]
    r["label"] = r["label"] or val(b, "itemLabel")
    r["birth"] = r["birth"] or val(b, "birth"); r["death"] = r["death"] or val(b, "death")
    r["birthplace"] = r["birthplace"] or val(b, "bplaceLabel")
    if val(b, "article"): r["enwiki"] = urllib.parse.unquote(val(b, "article").rsplit("/wiki/", 1)[1]).replace("_", " ")
batch("""SELECT ?item ?itemLabel ?birth ?death ?bplaceLabel ?article WHERE {
  VALUES ?item { %s }
  OPTIONAL { ?item wdt:P569 ?birth . }
  OPTIONAL { ?item wdt:P570 ?death . }
  OPTIONAL { ?item wdt:P19 ?bplace . }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,de,es,it,pt,ja,zh,ru,pl,sv" . }
}""", basic)
print("fetching citizenship")
def cit(b):
    r = info[qid(val(b, "item"))]
    if val(b, "cLabel") and val(b, "cLabel") not in r["citizenship"]: r["citizenship"].append(val(b, "cLabel"))
batch("""SELECT ?item ?cLabel WHERE {
  VALUES ?item { %s }
  ?item wdt:P27 ?c .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}""", cit)
print("fetching awards")
def award(b):
    a = {"award": val(b, "awardLabel"), "award_qid": qid(val(b, "award")), "year": (val(b, "time") or "")[:4] or None,
         "work": val(b, "workLabel"), "work_qid": qid(val(b, "work")) if val(b, "work") else None}
    lst = info[qid(val(b, "item"))]["awards"]
    if a not in lst: lst.append(a)
batch("""SELECT ?item ?award ?awardLabel ?time ?work ?workLabel WHERE {
  VALUES ?item { %s }
  ?item p:P166 ?st . ?st ps:P166 ?award .
  OPTIONAL { ?st pq:P585 ?time . }
  OPTIONAL { ?st pq:P1686 ?work . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,de,es,it" . }
}""", award)
print("fetching influences, teachers, students, movements and family")
PROPS = {"P737": "influenced by", "P1066": "student of", "P802": "student", "P135": "movement", "P26": "spouse", "P22": "father", "P25": "mother", "P40": "child", "P3373": "sibling"}
def rel(b):
    r = {"p": qid(val(b, "prop")), "qid": qid(val(b, "target")), "label": val(b, "targetLabel")}
    lst = info[qid(val(b, "item"))]["rel"]
    if r not in lst: lst.append(r)
batch("""SELECT ?item ?prop ?target ?targetLabel WHERE {
  VALUES ?item { %s }
  VALUES ?prop { wdt:P737 wdt:P1066 wdt:P802 wdt:P135 wdt:P26 wdt:P22 wdt:P25 wdt:P40 wdt:P3373 }
  ?item ?prop ?target .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,fr,de,es,it" . }
}""", rel)

out = {"retrieved": time.strftime("%Y-%m-%d"), "source": "Wikidata (CC0), https://www.wikidata.org", "properties": PROPS,
       "directors": {}, "people": info, "not_found": [[p["dir"], p["name"]] for p in persons if not p["qid"]]}
for p in found: out["directors"].setdefault(p["dir"], []).append({"qid": p["qid"], "name": p["name"], "found_by": p["how"]})
json.dump(out, open(os.path.join(HERE, "data", "wikidata.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
n_aw = sum(len(v["awards"]) for v in info.values()); n_rel = sum(len(v["rel"]) for v in info.values())
print("Saved data/wikidata.json: %d people, %d awards, %d relations. Not found: %d" % (len(info), n_aw, n_rel, len(out["not_found"])))
print("Done. Send this message to Claude, or run: python scripts/merge_wikidata.py and python build.py")
