"""Fetch film descriptions, ratings and ids from TMDB into data/tmdb.json.

Run this on your own machine (TMDB is not reachable from the build sandbox):

    Windows PowerShell:   $env:TMDB_API_KEY="your v3 key";  python scripts/fetch_tmdb.py
    macOS / Linux:        TMDB_API_KEY="your v3 key" python scripts/fetch_tmdb.py

Then run `python build.py`. The key is read from the environment and never written to disk.
The script can be stopped and restarted; it skips films it already has.
Posters and portraits are deliberately not fetched.
"""
import json, os, sys, time, difflib, unicodedata, urllib.parse, urllib.request, urllib.error, http.cookiejar

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTS = ["https://api.themoviedb.org/3", "https://api.tmdb.org/3"]   # the second is TMDB's own alternative address
API = HOSTS[0]
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
KEY, TOKEN = os.environ.get("TMDB_API_KEY"), os.environ.get("TMDB_TOKEN")
if not (KEY or TOKEN):
    sys.exit("Set TMDB_API_KEY (v3 key) or TMDB_TOKEN (v4 read access token) first.")

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

def fold(s): return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if c.isalnum())
def best(results, title, year):
    scored = []
    for r in results or []:
        y = int(r["release_date"][:4]) if r.get("release_date") else None
        sim = max(difflib.SequenceMatcher(None, fold(title), fold(r.get(k) or "")).ratio() for k in ("title", "original_title"))
        if year and y and abs(y - year) > 2: continue
        scored.append((sim + (0.15 if year and y == year else 0) + min(r.get("vote_count", 0), 500) / 5000, r))
    return max(scored, key=lambda x: x[0])[1] if scored else None

films = json.load(open(os.path.join(HERE, "data", "films.json"), encoding="utf-8"))
out_path = os.path.join(HERE, "data", "tmdb.json")
out = json.load(open(out_path, encoding="utf-8")) if os.path.exists(out_path) else {"films": {}, "not_found": []}
out.setdefault("films", {}); out.setdefault("not_found", [])
out["not_found"] = []
todo = [f for f in films if f["id"] not in out["films"]]
print(len(films), "films,", len(todo), "to fetch")
test, errors = None, []
for host in HOSTS:
    API = host
    try:
        test = get("/search/movie", tries=2, query="Citizen Kane", year=1941)
        if test and test.get("results"): break
        errors.append(host + ": empty answer"); test = None
    except Exception as e:
        errors.append(host + ": " + str(e)); test = None
if not test:
    sys.exit("Cannot get a normal answer from TMDB, so nothing was changed.\n" + "\n".join(errors) + "\nSend these lines to Claude.")
print("Using", API)
print("Connection test passed: found", test["results"][0]["title"])
failed = []
for n, f in enumerate(todo, 1):
    try:
        hit = None
        for params in ({"primary_release_year": f["year"]}, {"year": f["year"]}, {}) if f["year"] else ({},):
            res = get("/search/movie", query=f["title"], include_adult="false", **params)
            hit = best(res.get("results") if res else None, f["title"], f["year"])
            if hit: break
        if not hit:
            out["not_found"].append(f["id"])
        else:
            det = get("/movie/%d" % hit["id"]) or {}
            out["films"][f["id"]] = {"tmdb_id": hit["id"], "imdb_id": det.get("imdb_id"), "matched_title": hit.get("title"), "release_date": hit.get("release_date"),
                                     "overview": hit.get("overview") or "", "vote_average": hit.get("vote_average"), "vote_count": hit.get("vote_count")}
    except Failed as e:
        failed.append(f["id"])
        if len(failed) == 1 or len(failed) % 25 == 0: print("  request failed for", f["title"], "-", e)
        if len(failed) >= 60 and len(failed) > n * 0.5:
            json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            sys.exit("Too many failed requests, stopped. Last error: %s\nWhat was fetched is saved; run the script again later." % e)
    if n % 40 == 0 or n == len(todo):
        json.dump(out, open(out_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"{n}/{len(todo)} done, {len(out['films'])} matched, {len(out['not_found'])} not on TMDB, {len(failed)} failed (will retry next run)")
    time.sleep(0.05)
print("Saved", out_path, "- now run: python build.py")
print("Check data/tmdb.json for wrong matches: compare matched_title and release_date with data/films.json.")
