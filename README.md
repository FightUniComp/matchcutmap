# Auteur Atlas

Trace the influences that connect film directors. Website: https://auteuratlas.org

An interactive 2D map of film directors. Distance means similarity of style, shaded
areas are movements, circle size is influence, arrows show who influenced whom.

## What is verified and what is draft

| Data | Status |
|---|---|
| Director ranks (TSPDT top 250, 2026) | From the source |
| Film ranks: TSPDT 1,000 Greatest Films (2026), Sight and Sound critics' poll (2022) | From the source |
| House of Tabula film studies watchlist membership | From the source |
| Cannes top prize (Grand Prix du Festival, Palme d'Or), all 103 winners 1939 to 2026 | From the source; every fact that mentions the Palme d'Or was checked against it |
| Film descriptions, ratings, filmographies, birth and death dates (TMDB) | From the source; a film match is kept only when TMDB credits our director for it |
| Page references to The Oxford History of World Cinema | Found by text search in an OCR of the book; page numbers are scan pages, not printed page numbers |
| Descriptions, facts, techniques, style scores, movements, most influence links | Draft, written from general film knowledge, not yet checked |

## Layout of this repo

| Path | What it is |
|---|---|
| `data/directors.json` | Profiled directors: country, movements (first clustered one decides the map area), techniques, eight style scores from 1 to 10 |
| `data/facts.json` | Per director: one-line signature, longer description, facts. Each fact has a `status` (`verified` or `draft`) and a `source` |
| `data/cannes.json` | Winners of the top prize at Cannes |
| `data/films.json` | Every film from the lists, with director ids, year and ranks, plus a few films per director added by hand (`"added": "hand"`) for directors who are on no list |
| `data/directory.json` | Directors without a profile yet (searchable, not on the map); currently empty |
| `data/influence.json` | Directed influence links with an optional note |
| `data/techniques.json`, `data/movements.json`, `data/dimensions.json` | The closed vocabularies |
| `data/tspdt.json` | Rank of each director in the TSPDT top 250 |
| `data/book.json` | Scan pages of the Oxford History where each director is named, and pages where both ends of an influence link are named together |
| `data/sources.json` | The sources and what each is used for |
| `data/tmdb.json` | Created by `scripts/fetch_tmdb.py`: per film the TMDB match, description, rating, ids. `rejected` lists TMDB ids that proved to be the wrong film. Not committed |
| `data/people.json` | Created by `scripts/fetch_tmdb.py`: per director the TMDB person record (birth, death, place of birth) and everything they directed. Not committed |
| `scripts/fetch_tmdb.py` | Fetches TMDB data. Needs your API key in the environment |
| `scripts/check_imdb.py` | Checks our films against your own copy of the IMDb datasets and writes a local report. IMDb data itself is never stored in this repo |
| `template.html` | The page: markup, styles and script |
| `build.py` | Reads `data/`, computes similarity and layout, writes `site/index.html` |
| `site/index.html`, `docs/index.html` | The built page, written twice. GitHub Pages serves `docs/`; `docs/CNAME` holds the domain |
| `scripts/build_db.py` | Builds `database/auteur-atlas.sqlite` and one CSV per table in `database/csv/` from `data/` |
| `assets/` | `logo.png` (original), `logo-light.png` (recoloured for the dark page), `favicon.png` |

## Build

    pip install numpy scikit-learn
    python build.py --report

## The database

    python scripts/build_db.py

Writes `database/auteur-atlas.sqlite`. Open it with DB Browser for SQLite (https://sqlitebrowser.org).
This public build holds our own data plus TMDB and IMDb ids for linking. TMDB's terms allow
showing its data with attribution but not redistributing it, so `python scripts/build_db.py
--with-tmdb` writes a fuller local copy, `database/auteur-atlas-full.sqlite`, with TMDB
descriptions, ratings, birth dates and filmographies. That file and the TMDB JSON files are
not committed; the built page shows the TMDB data with the required attribution.
Tables: directors, films, film_directors, awards, movements, director_movements, techniques,
director_techniques, style_scales, influences, facts, book_mentions, sources, and once TMDB has
been fetched, director_people and filmography.
The view `to_verify` lists every claim still marked draft. The JSON files stay the source of
truth: edit those and rebuild.

## Add TMDB data (run on your own machine)

    PowerShell:  $env:TMDB_API_KEY="your key"; python scripts/fetch_tmdb.py; python build.py

Step 1 matches every film and keeps a match only if TMDB credits one of our directors.
Step 2 finds each director's TMDB person record through those films and stores their
birth and death dates and filmography. The page then shows full filmographies, ranks the
key films by list rank and then by TMDB audience, and links straight to Letterboxd and IMDb.

## Check against IMDb (optional, local only)

    python scripts/check_imdb.py PATH/title.basics.tsv PATH/title.crew.tsv

Uses your own download of https://datasets.imdbws.com to flag wrong TMDB matches, years that
are far off and director credits that do not fit. IMDb's licence allows personal,
non-commercial use only and forbids republishing its data, so the report stays on your
machine and nothing from these files goes into the site or the repo.
TMDB requires the notice "This product uses the TMDB API but is not endorsed or
certified by TMDB", which the page shows once the data is present.

## How similarity works

Three ingredients, weighted at the top of `build.py`:

- techniques in common, with rare techniques counting more (42%)
- closeness on the eight style scores (23%)
- movements in common (35%), historical movements counting more than critical categories

## Editing rules

- Only use technique and movement ids that exist in the vocabulary files. The build fails on unknown ids.
- Add a technique only if at least two directors will carry it.
- Never commit API keys.
- Do not commit the text of the book or of the list pages; only ranks, titles and page numbers.
