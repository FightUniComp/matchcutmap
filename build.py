"""Auteur Atlas build script.

Reads the JSON files in data/, computes how similar every pair of profiled
directors is, lays them out in 2D so that distance means similarity, and writes
a single self-contained page to site/index.html.

Usage:  python build.py            (add --report to print a sanity check)
Needs:  numpy, scikit-learn
"""
import json, math, sys, os, statistics
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

# ---------- validate ----------
ids = [d["id"] for d in D]
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
    if tm:
        for a, b in (("overview", "ov"), ("vote_average", "r"), ("tmdb_id", "tid"), ("imdb_id", "im")):
            if tm.get(a): o[b] = tm[a]
    return o
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
    pg = BOOK["pages"].get(i, [])
    if pg:
        out.append(f"Named on {plural(len(pg), 'page')} of The Oxford History of World Cinema.")
    return out
def era_of(d):
    ys = [f["year"] for f in by_dir.get(d["id"], []) if f["year"]]
    y = statistics.median(ys) if ys else (d["born"] + 40 if d.get("born") else 1960)
    return next(k for k, (lim, _) in enumerate(ERAS) if y <= lim)
def span(i):
    ys = [f["year"] for f in by_dir.get(i, []) if f["year"]]
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

def director_out(i, d):
    fl = by_dir.get(d["id"], [])
    fx = F.get(d["id"], {})
    o = {"id": d["id"], "name": d["name"], "country": d["country"], "movements": d["movements"],
         "films": [film_out(f) for f in fl[:KEY_FILMS]], "nfilms": len(fl), "span": span(d["id"]), "rank": ranks.get(d["id"]),
         "sig": fx.get("signature", ""), "desc": fx.get("description", ""), "facts": [[f["text"], 1 if f["status"] == "verified" else 0] for f in fx.get("facts", [])], "lists": list_facts(d["id"]),
         "tags": d["techniques"], "dims": [d["scores"][k] for k in keys],
         "x": round(float(X[i, 0]), 1), "y": round(float(X[i, 1]), 1), "r": round(float(R[i]), 1),
         "out": out_deg[d["id"]], "era": era_of(d), "tier": tier(d["id"]), "near": near[d["id"]]}
    if d.get("born"): o["born"] = d["born"]
    return o

def evidence(e):
    return BOOK["pairs"].get(e["from"] + "|" + e["to"]) or BOOK["pairs"].get(e["to"] + "|" + e["from"]) or []

data = {
 "w": W, "h": H, "eras": [lab for _, lab in ERAS], "sources": SOURCES, "hasTmdb": bool(TMDB["films"]),
 "counts": {"films": len(FILMS), "tspdt": sum(1 for f in FILMS if f["tspdt"]), "ss": sum(1 for f in FILMS if f["sight_and_sound"]), "hot": sum(1 for f in FILMS if f["house_of_tabula"]), "cannes": len(CANNES), "factsChecked": sum(1 for v in F.values() for f in v.get("facts", []) if f["status"] == "verified"), "facts": sum(len(v.get("facts", [])) for v in F.values()),
            "notes": sum(1 for e in I if e["note"]), "evidence": sum(1 for e in I if evidence(e))},
 "rankSource": {"name": TSPDT["source"], "edition": TSPDT["edition"], "url": TSPDT["url"]},
 "techniques": {k: {"name": v["name"], "cat": v["category"], "def": v["definition"]} for k, v in T.items()},
 "movements": {k: {"name": v["name"], "kind": v["kind"], "period": v["period"], "desc": v["description"],
                   "members": [d["id"] for d in D if k in d["movements"]],
                   "primary": [ids[i] for i in groups.get(k, [])]} for k, v in MV.items()},
 "dims": [{"key": m["key"], "lo": m["low"], "hi": m["high"]} for m in DIMS],
 "directors": [director_out(i, d) for i, d in enumerate(D)],
 "directory": [{"id": e["id"], "name": e["name"], "films": [film_out(f) for f in by_dir.get(e["id"], [])[:KEY_FILMS]]} for e in DIRECTORY],
 "influence": [dict({"s": e["from"], "t": e["to"], "note": e["note"]}, **({"ev": evidence(e)[:3]} if evidence(e) else {})) for e in I],
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
