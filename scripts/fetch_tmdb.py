"""Fetch film data and director filmographies from TMDB.

Run this on your own machine (TMDB is not reachable from the build sandbox):

    Windows PowerShell:   $env:TMDB_API_KEY="your v3 key";  python scripts/fetch_tmdb.py
    macOS / Linux:        TMDB_API_KEY="your v3 key" python scripts/fetch_tmdb.py

Step 1, films: finds every film in data/films.json on TMDB and keeps a match only when
TMDB credits one of our directors for it. Writes data/tmdb.json.
Step 2, people: finds each director's TMDB person record through the credits of their
films, then stores birth and death dates and everything they directed. Writes
data/people.json. A film match whose TMDB credits do not name our director is thrown
out and searched again.

Step 3, collaborators: reads the credits of each director's best-known films (up to 10)
and stores who worked with them on at least two: cinematographers, composers, editors,
writers, production designers and leading actors.

Options: --films, --people or --collab (run one step only), --refresh (redo every director),
--only=id1,id2 (redo just these directors).
The key is read from the environment and never written to disk. The script can be
stopped and restarted; it skips what it already has. No posters or portraits are fetched.
"""
import json, os, re, sys, time, difflib, unicodedata, urllib.parse, urllib.request, urllib.error, http.cookiejar

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTS = ["https://api.themoviedb.org/3", "https://api.tmdb.org/3"]   # the second is TMDB's own alternative address
API = HOSTS[0]
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
KEY, TOKEN = os.environ.get("TMDB_API_KEY"), os.environ.get("TMDB_TOKEN")
ARGS = set(sys.argv[1:])

class Failed(Exception): pass
LAST = {"error": ""}
def get(path, tries=6, **params):
    if KEY: params["api_key"] = KEY
    req = urllib.request.Request(API + path + "?" + urllib.parse.urlencode(params), headers={"Accept": "application/json", "User-Agent": "AuteurAtlas/1.0 (auteuratlas.org)"})
    if TOKEN and not KEY: req.add_header("Authorization", "Bearer " + TOKEN)
    for attempt in range(tries):
        try:
            with OPENER.open(req, timeout=25) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            LAST["error"] = "HTTP %d %s | redirect to: %s" % (e.code, str(e.reason).splitlines()[0], e.headers.get("Location"))
            if e.code == 404: return None
            if e.code == 401: sys.exit("TMDB rejected the key (401). Check TMDB_API_KEY.")
            time.sleep(3 + 3 * attempt if e.code == 429 else 1 + attempt)
        except Exception as e:
            LAST["error"] = "%s: %s" % (type(e).__name__, e)
            time.sleep(1 + attempt)
    raise Failed(LAST["error"])

def fold(s): return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if c.isalnum() and ord(c) < 128)
def tokens(s):
    t = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if ord(c) < 128)    # drops accents
    return "".join(c if c.isalnum() else " " for c in t).split()
def same_person(tmdb_name, names):
    """True if a TMDB name is one of our names. Lenient on transliteration, strict enough to catch a wrong film."""
    a = tokens(tmdb_name)
    for n in names:
        b = tokens(n)
        if not a or not b: continue
        if fold(tmdb_name) == fold(n) or difflib.SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() >= 0.85: return True
        if len(a[-1]) >= 3 and a[-1] == b[-1]: return True          # same family name: Oleksandr / Alexander Dovzhenko
        if len(a) >= 2 and len(b) >= 2 and (set(a) <= set(b) or set(b) <= set(a)): return True
    return False

def save(path, obj): json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def load(name, default=None):
    p = os.path.join(HERE, "data", name + ".json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else default

films = load("films"); directors = load("directors")
names = {d["id"]: (d.get("members") or [d["name"]]) + d.get("aka", []) for d in directors}   # aka: other names TMDB may use
tm_path, pp_path = os.path.join(HERE, "data", "tmdb.json"), os.path.join(HERE, "data", "people.json")
TM = load("tmdb", {}) ; TM.setdefault("films", {}); TM.setdefault("rejected", {}); TM["not_found"] = []
PP = load("people", {}) ; PP.setdefault("directors", {}); PP.setdefault("suspicious", {})

def connect():
    global API
    errors = []
    for host in HOSTS:
        API = host
        try:
            test = get("/search/movie", tries=2, query="Citizen Kane", year=1941)
            if test and test.get("results"):
                print("Using", API, "- connection test passed"); return
            errors.append(host + ": empty answer")
        except Exception as e:
            errors.append(host + ": " + str(e))
    sys.exit("Cannot get a normal answer from TMDB, so nothing was changed.\n" + "\n".join(errors) + "\nSend these lines to Claude.")

def candidates(results, title, year, skip, late=False):
    """late=True: also accept a release up to 15 years after the year we have (films banned or released late),
    if the title is a close match; the director credit is still checked afterwards."""
    scored = []
    for r in results or []:
        if r["id"] in skip: continue
        y = int(r["release_date"][:4]) if r.get("release_date") else None
        if year and y and (y - year > 15 or y - year < -2 if late else abs(y - year) > 2): continue
        if late and max(difflib.SequenceMatcher(None, fold(title), fold(r.get(k) or "")).ratio() for k in ("title", "original_title")) < 0.85: continue
        sim = max(difflib.SequenceMatcher(None, fold(title), fold(r.get(k) or "")).ratio() for k in ("title", "original_title"))
        if len(fold(title)) >= 2 and any(fold(r.get(k) or "").startswith(fold(title)) for k in ("title", "original_title")): sim = max(sim, 0.6)   # "Salò" -> "Salò, or the 120 Days of Sodom"
        scored.append((sim + (0.15 if year and y == year else 0) + min(r.get("vote_count", 0), 500) / 5000, r))
    return [r for s, r in sorted(scored, key=lambda x: -x[0]) if s >= 0.55]

def variants(t):
    """Titles to search for: 'Partie de campagne (A Day in the Country)', 'Red Wood Pigeon (aka Palombella rossa)', 'X aka Y'."""
    vs = [t]
    m = re.match(r"^(.*?)\s*\((?:aka\s+|a\.k\.a\.\s+|episode of\s+)?(.+?)\)\s*$", t, re.I)
    if m: vs += [m.group(1)] + ([] if m.group(0).lower().find("episode of") >= 0 else [m.group(2)])
    for sep in (" aka ", " a.k.a. "):
        if sep in t.lower(): i = t.lower().index(sep); vs += [t[:i], t[i + len(sep):]]
    return list(dict.fromkeys(v.strip() for v in vs if v.strip()))

def fetch_films():
    todo = [f for f in films if f["id"] not in TM["films"]]
    TM["not_found"] = [i for i in TM.get("not_found", []) if i not in {f["id"] for f in todo}]
    print("Films:", len(films), "in the data,", len(todo), "to look up")
    failed = []
    for n, f in enumerate(todo, 1):
        ours = [x for d in f["directors"] for x in names.get(d, [])]
        skip = set(TM["rejected"].get(f["id"], []))
        try:
            hit, seen = None, set()
            tries = [(q, p, False) for q in variants(f["title"]) + f.get("alt", []) for p in (({"primary_release_year": f["year"]}, {"year": f["year"]}, {}) if f["year"] else ({},))]
            tries += [(q, {}, True) for q in variants(f["title"]) + f.get("alt", [])] if f["year"] else []
            for q, params, late in tries:
                res = get("/search/movie", query=q, include_adult="false", **params) or {}
                for r in candidates(res.get("results"), q, f["year"], skip | seen, late)[:3]:
                    seen.add(r["id"])
                    det = get("/movie/%d" % r["id"], append_to_response="credits") or {}
                    crew = [c["name"] for c in (det.get("credits") or {}).get("crew", []) if c.get("job") == "Director"]
                    if not ours or any(same_person(c, ours) for c in crew):
                        hit = (r, det, crew); break
                if hit: break
            if not hit:
                TM["not_found"].append(f["id"])
            else:
                r, det, crew = hit
                TM["films"][f["id"]] = {"tmdb_id": r["id"], "imdb_id": det.get("imdb_id"), "matched_title": r.get("title"), "release_date": r.get("release_date"),
                                        "overview": r.get("overview") or "", "vote_average": r.get("vote_average"), "vote_count": r.get("vote_count"),
                                        "tmdb_directors": crew, "checked": True}
        except Failed as e:
            failed.append(f["id"])
            if len(failed) == 1 or len(failed) % 25 == 0: print("  request failed for", f["title"], "-", e)
            if len(failed) >= 60 and len(failed) > n * 0.5:
                save(tm_path, TM); sys.exit("Too many failed requests, stopped. Last error: %s\nWhat was fetched is saved; run the script again later." % e)
        if n % 40 == 0 or n == len(todo):
            save(tm_path, TM)
            print(f"  {n}/{len(todo)}: {len(TM['films'])} matched, {len(TM['not_found'])} not found, {len(failed)} failed (retried next run)")
        time.sleep(0.03)
    save(tm_path, TM)

def trim(s, n=300):
    s = (s or "").strip()
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "..."

def fetch_people():
    by_dir = {}
    for f in films:
        for d in f["directors"]: by_dir.setdefault(d, []).append(f)
    only = next((a.split("=", 1)[1].split(",") for a in ARGS if a.startswith("--only=")), None)
    todo = [d for d in directors if ((d["id"] in only) if only else ("--refresh" in ARGS or d["id"] not in PP["directors"]))]
    print("People:", len(directors), "directors,", len(todo), "to look up")
    rejected = 0
    for n, d in enumerate(todo, 1):
        ours = names[d["id"]]
        lst = sorted(by_dir.get(d["id"], []), key=lambda f: (f.get("added") == "hand", not f.get("tspdt"), -(TM["films"].get(f["id"], {}).get("vote_count") or 0)))
        found = {}
        try:
            for f in [f for f in lst if f["id"] in TM["films"]][:5]:
                m = TM["films"][f["id"]]
                cr = get("/movie/%d/credits" % m["tmdb_id"]) or {}
                crew = [(c["id"], c["name"]) for c in cr.get("crew", []) if c.get("job") == "Director"]
                hits = [(i, nm) for i, nm in crew if same_person(nm, ours)]
                for i, nm in hits: found[i] = found.get(i, (nm, 0))[0], found.get(i, (nm, 0))[1] + 1
                credited = [x for c in f["directors"] for x in names.get(c, [])]    # all our directors of this film, co-directors included
                if crew and not hits and not any(same_person(nm, credited) for _, nm in crew):   # TMDB says someone else made it: wrong match
                    PP["suspicious"][f["id"]] = {"title": f["title"], "year": f["year"], "matched": m.get("matched_title"), "tmdb_directors": [nm for _, nm in crew]}
                    TM["rejected"].setdefault(f["id"], []).append(m["tmdb_id"]); TM["films"].pop(f["id"]); rejected += 1
            how = "credits"
            if not found:                                    # no usable film: search the name, directors only
                how = "search"
                for nm in ours:
                    res = get("/search/person", query=nm) or {}
                    ok = [p for p in res.get("results", []) if same_person(p["name"], [nm])]
                    ok.sort(key=lambda p: (p.get("known_for_department") != "Directing", fold(p["name"]) != fold(nm), -(p.get("popularity") or 0)))
                    if ok: found[ok[0]["id"]] = (ok[0]["name"], 0)
            persons, filmo = [], {}
            ranked = sorted(found.items(), key=lambda kv: -kv[1][1])
            keep = ranked if len(ours) > 1 else ranked[:1]
            for pid, (nm, k) in keep:
                p = get("/person/%d" % pid, append_to_response="movie_credits") or {}
                persons.append({"tmdb_id": pid, "name": p.get("name") or nm, "imdb_id": p.get("imdb_id"), "birthday": p.get("birthday"), "deathday": p.get("deathday"),
                                "place_of_birth": p.get("place_of_birth"), "films_matched": k})
                for c in (p.get("movie_credits") or {}).get("crew", []):
                    if c.get("job") != "Director" or c["id"] in filmo: continue
                    vc = c.get("vote_count") or 0
                    filmo[c["id"]] = {"tmdb_id": c["id"], "title": c.get("title"), "original_title": c.get("original_title"), "release_date": c.get("release_date") or None,
                                      "vote_average": c.get("vote_average"), "vote_count": vc, "overview": trim(c.get("overview")) if vc >= 20 else ""}
            PP["directors"][d["id"]] = {"how": how if persons else "not found", "persons": persons,
                                        "films": sorted(filmo.values(), key=lambda x: x["release_date"] or "9999")}
        except Failed as e:
            print("  request failed for", d["name"], "-", e)
        if n % 20 == 0 or n == len(todo):
            save(pp_path, PP); save(tm_path, TM)
            nf = sum(1 for v in PP["directors"].values() if v["how"] == "not found")
            print(f"  {n}/{len(todo)} directors done, {nf} not found, {rejected} wrong film matches thrown out")
        time.sleep(0.03)
    save(pp_path, PP); save(tm_path, TM)
    return rejected

ROLES = {"Director of Photography": "Cinematography", "Original Music Composer": "Music", "Music": "Music", "Editor": "Editing",
         "Screenplay": "Writing", "Writer": "Writing", "Production Design": "Production design"}
def fetch_collab():
    by_dir = {}
    for f in films:
        for d in f["directors"]: by_dir.setdefault(d, []).append(f)
    only = next((a.split("=", 1)[1].split(",") for a in ARGS if a.startswith("--only=")), None)
    todo = [d for d in directors if PP["directors"].get(d["id"], {}).get("persons")
            and ((d["id"] in only) if only else ("--refresh" in ARGS or "collab" not in PP["directors"][d["id"]]))]
    print("Collaborators:", len(todo), "directors to look up")
    for n, d in enumerate(todo, 1):
        rec = PP["directors"][d["id"]]; me = {p["tmdb_id"] for p in rec["persons"]}
        picks = [TM["films"][f["id"]]["tmdb_id"] for f in by_dir.get(d["id"], []) if f["id"] in TM["films"]]
        picks += [x["tmdb_id"] for x in sorted(rec.get("films", []), key=lambda x: -(x.get("vote_count") or 0)) if (x.get("vote_count") or 0) >= 20]
        picks = list(dict.fromkeys(picks))[:10]
        tally = {}
        try:
            for tid in picks:
                cr = get("/movie/%d/credits" % tid) or {}
                people = [(c["id"], c["name"], ROLES.get(c.get("job"))) for c in cr.get("crew", [])]
                people += [(c["id"], c["name"], "Acting") for c in sorted(cr.get("cast", []), key=lambda c: c.get("order", 99))[:4]]
                for pid, nm, role in people:
                    if role and pid not in me: tally.setdefault((pid, role), {"name": nm, "films": set()})["films"].add(tid)
            rec["collab"] = sorted([{"tmdb_id": pid, "name": v["name"], "role": role, "films": sorted(v["films"])} for (pid, role), v in tally.items() if len(v["films"]) >= 2],
                                   key=lambda c: (c["role"], -len(c["films"])))
            rec["collab_films"] = picks
        except Failed as e:
            print("  request failed for", d["name"], "-", e)
        if n % 20 == 0 or n == len(todo):
            save(pp_path, PP); print(f"  {n}/{len(todo)} directors done")
        time.sleep(0.02)
    save(pp_path, PP)

if not (KEY or TOKEN): sys.exit("Set TMDB_API_KEY (v3 key) or TMDB_TOKEN (v4 read access token) first.")
connect()
steps = [a for a in ("--films", "--people", "--collab") if a in ARGS] or ["--films", "--people", "--collab"]
if "--films" in steps: fetch_films()
if "--people" in steps:
    if fetch_people(): print("Searching again for the films whose match was wrong:"); fetch_films()
if "--collab" in steps: fetch_collab()
print("Done. Saved data/tmdb.json and data/people.json. Now run: python build.py")
