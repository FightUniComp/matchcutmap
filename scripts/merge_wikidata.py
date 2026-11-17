"""Fold data/wikidata.json into our own data files.

    python scripts/merge_wikidata.py [--dry-run]

- 'influenced by' (P737) between two directors on the map becomes an influence link with
  source 'wikidata'; a link we already had gains that source, which counts as checked.
- 'student of' (P1066) and 'student' (P802) become links with a note saying who studied with whom.
- A draft fact about a major award is marked checked when Wikidata lists that award for the
  director with the same film or year.
Links that Wikidata records in the opposite direction to ours are reported, not changed.
A director with LONG or more 'influenced by' entries in Wikidata (such lists tend to be
favourite directors rather than influences) only confirms links we already have.
"""
import json, os, re, sys, unicodedata

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def load(n): return json.load(open(os.path.join(HERE, "data", n + ".json"), encoding="utf-8"))
def dump(n, o): json.dump(o, open(os.path.join(HERE, "data", n + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
def low(s): return unicodedata.normalize("NFC", (s or "").lower())

WD, D, I, F = load("wikidata"), load("directors"), load("influence"), load("facts")
name = {d["id"]: d["name"] for d in D}
q2d = {p["qid"]: did for did, ps in WD["directors"].items() for p in ps if did in name}
edges = {(e["from"], e["to"]): e for e in I}
added, confirmed, reverse, held = [], [], [], set()
LONG = 10
n737 = {did: sum(1 for p in ps for r in WD["people"].get(p["qid"], {}).get("rel", []) if r["p"] == "P737") for did, ps in WD["directors"].items()}

def link(a, b, note, confirm_only=False):
    """a influenced b, according to Wikidata"""
    if a == b: return
    e = edges.get((a, b))
    if not e and confirm_only: held.add(b); return
    if e:
        src = set(e.get("sources", [])) | {"wikidata"}
        if "wikidata" not in e.get("sources", []): confirmed.append((a, b))
        e["sources"] = sorted(src)
        if note and not e.get("note"): e["note"] = note
        return
    if (b, a) in edges and "wikidata" not in edges[(b, a)].get("sources", []): reverse.append((a, b))
    e = {"from": a, "to": b, "note": note, "sources": ["wikidata"]}
    I.append(e); edges[(a, b)] = e; added.append((a, b))

for did, ps in WD["directors"].items():
    if did not in name: continue
    for p in ps:
        for r in WD["people"].get(p["qid"], {}).get("rel", []):
            other = q2d.get(r["qid"])
            if not other or other == did: continue
            if r["p"] == "P737": link(other, did, "", confirm_only=n737.get(did, 0) >= LONG)
            elif r["p"] == "P1066": link(other, did, f"{name[did]} studied with {name[other]}.")
            elif r["p"] == "P802": link(did, other, f"{name[other]} studied with {name[did]}.")

# award facts
PAIRS = [("palme d'or", ["palme d'or"]), ("golden lion", ["golden lion"]), ("golden bear", ["golden bear"]), ("silver lion", ["silver lion"]),
         ("silver bear", ["silver bear"]), ("caméra d'or", ["caméra d'or", "camera d'or"]), ("grand prix at cannes", ["grand prix"]),
         ("jury prize at cannes", ["jury prize"]), ("best director at cannes", ["best director", "mise en scène"]),
         ("golden shell", ["golden shell"]), ("golden leopard", ["golden leopard"]),
         ("best director oscar", ["academy award for best director"]), ("oscar for best director", ["academy award for best director"]),
         ("best director oscars", ["academy award for best director"]), ("screenplay oscar", ["screenplay", "writing"]),
         ("oscar for original screenplay", ["original screenplay"]), ("oscar for adapted screenplay", ["adapted screenplay"]),
         ("honorary oscar", ["honorary award"]), ("best animated feature", ["animated feature"])]
checked = []
for did, ps in WD["directors"].items():
    awards = [a for p in ps for a in WD["people"].get(p["qid"], {}).get("awards", [])]
    if did not in F or not awards: continue
    for f in F[did].get("facts", []):
        if f["status"] != "draft": continue
        t = low(f["text"])
        for fk, aks in PAIRS:
            if fk not in t: continue
            for a in awards:
                al, w, y = low(a["award"]), low(a.get("work")), a.get("year") or ""
                if any(k in al for k in aks) and ((len(w) >= 3 and w in t) or (y and y in t)):
                    f["status"], f["source"] = "verified", "wikidata"; checked.append((did, f["text"])); break
            if f["status"] == "verified": break

print(f"{len(added)} new influence links from Wikidata, {len(confirmed)} existing links confirmed, {len(checked)} award facts checked")
for a, b in reverse: print(f"  opposite direction: Wikidata says {name[a]} influenced {name[b]}; we had the reverse")
for d in sorted(held): print(f"  {name[d]}: {n737[d]} 'influenced by' entries in Wikidata, so only existing links were confirmed")
if "--dry-run" not in sys.argv:
    dump("influence", I); dump("facts", F); print("Saved data/influence.json and data/facts.json. Now run: python build.py")
