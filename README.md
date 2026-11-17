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
| Birth and death, birthplace, awards, 'influenced by', teachers, students, family (Wikidata) | From the source; Wikidata is public domain (CC0). Influence links it records are marked "Recorded in Wikidata" and count as checked |
| Oscar winners: Best Picture, Best Director, Best International Feature Film, 1927/28 to 2025 | Compiled by hand; the 2025 winners were checked against press reports and the international list against a partial copy of Wikipedia's list. Corrections welcome |
| Cahiers du cinéma: 100 films for an ideal cinémathèque (2008) | From the published list; tied ranks from the vote counts (Moonfleet is missing from the vote-count page and was placed by the published order) |
| Cahiers du cinéma: top 10 of the year, 1951 to 2025, and best of the 1990s, 2000s and 2010s | From Wikipedia's collection of the lists |
| The House of Tabula's cinematic complexity iceberg (68 films, eight tiers) | From an IMDb user's copy of the channel's video |
| Page references to The Oxford History of World Cinema | Found by text search in an OCR of the book; page numbers are scan pages, not printed page numbers |
| Descriptions, facts, techniques, style scores, movements, most influence links | Draft, written from general film knowledge, not yet checked |

## Layout of this repo

| Path | What it is |
|---|---|
| `data/directors.json` | Profiled directors: country, movements (first clustered one decides the map area), techniques, eight style scores from 1 to 10 |
| `data/facts.json` | Per director: one-line signature, longer description, facts. Each fact has a `status` (`verified` or `draft`) and a `source` |
| `data/cannes.json` | Winners of the top prize at Cannes |
| `data/oscars.json` | Oscar winners for Best Picture, Best Director and Best International Feature Film |
| `data/iceberg.json` | The House of Tabula's cinematic complexity iceberg, by tier |
| `data/cahiers.json` | Cahiers du cinéma's 100 films for an ideal cinémathèque (2008, with vote counts) and its annual and decade top 10 lists |
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
| `data/wikidata.json` | Created by `scripts/fetch_wikidata.py`: Wikidata facts per director. CC0, committed |
| `scripts/fetch_wikidata.py` | Fetches Wikidata facts (no key needed) |
| `scripts/merge_wikidata.py` | Turns Wikidata influence and teacher links into influence links and checks award facts |
| `scripts/check_imdb.py` | Checks our films against your own copy of the IMDb datasets and writes a local report. IMDb data itself is never stored in this repo |
| `scripts/imdb_personal.py` | Makes a private file of IMDb ratings from your own copy of the IMDb datasets, to import in your browser. Writes `personal/`, which is not committed |
| `template.html` | The page: markup, styles and script |
| `build.py` | Reads `data/`, computes similarity and layout, writes the page to `site/` and `docs/` |
| `docs/index.html`, `docs/d/` | What GitHub Pages serves (`docs/CNAME` holds the domain). `index.html` holds the map and everything the views across directors need; what only a director's panel shows (films with their descriptions, filmography, collaborators, texts, facts, awards, nearest neighbours) is split over 64 small files in `docs/d/`, fetched when that panel opens or the pointer rests on the director |
| `site/index.html` | The same page as one self-contained file with everything inside, for opening straight from disk |
| `scripts/build_db.py` | Builds `database/auteur-atlas.sqlite` and one CSV per table in `database/csv/` from `data/` |
| `assets/` | `logo.png` (original), `logo-light.png` (recoloured for the dark page), `favicon.png` |

## Build

    pip install numpy scikit-learn
    python build.py --report

The split page needs a web server, because browsers do not let a page opened from
disk fetch other files. To try it locally: `python -m http.server --directory docs`,
then open http://localhost:8000. Or open `site/index.html`, which needs nothing.

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
birth and death dates and filmography. Step 3 reads the credits of each director's
best-known films and stores their regular collaborators (cinematography, editing, music,
writing, production design, leading actors). The page then shows full filmographies, ranks the
key films by list rank and then by TMDB audience, and links straight to Letterboxd and IMDb.

## Add Wikidata (run on your own machine, after TMDB)

    python scripts/fetch_wikidata.py
    python scripts/merge_wikidata.py
    python build.py

`merge_wikidata.py` turns 'influenced by' and teacher links between directors on the map
into influence links and marks award facts as checked. A director with ten or more 'influenced
by' entries in Wikidata (those lists tend to be favourite directors) only confirms links we
already have.

## Features of the page

- Shareable links: `#ozu` (a director), `#m/french-new-wave` (a movement), `#t/long-take`
  (a technique), `#g/r:East Asia` or `#g/c:Japan` (a region or country), `#path/ozu/bigan`
  (a traced connection). The browser's back button steps through what you looked at.
- Trace a connection: the shortest chain of influence between two directors, falling back
  to style similarity where no influence chain exists.
- Highlight a region or country, "Surprise me", Escape to clear.
- Timeline: the same dots glide into a timeline, left to right by the median year of each
  director's films, one row per region. Links work there too (`#timeline/ozu`). A selected
  director's career is drawn as a line from first to last film, with a tick per film (key
  films in gold); a highlighted movement shades its period.
- Decades: click a decade on the timeline, or pick one on the start panel (`#d/1960`): who
  was at work, the decade's most acclaimed films, the movements active then, and whose first
  films fall in it.
- Lineage: who came before and after a director, one to three generations of influence
  (`#lin/ozu`, `#lin/ozu/3`). On the timeline it runs from left to right.
- Ratings across the career: a chart in each director's panel with the TMDB rating of every
  film that has 20 or more votes, key films in gold.
- Compare two directors side by side (`#cmp/bergman/tarkovsky`): style scales, shared and
  separate techniques, movements, how they connect, shared crew.
- Your films: mark films as seen or as want to see, or import what you have watched and your
  watchlist from a Letterboxd export (the .zip) or an IMDb export (.csv). `#want` lists the
  films you want to see. Your own ratings show on the film cards, the
  directors you have watched light up on the map (`#mine`), and "Next for you" suggests
  directors close in style or linked by influence to the ones you have seen. All of this is
  kept in your browser only; Export and Import move it to another browser.
- Lists and awards: Cannes, the Oscars (Best Picture, Director, International Feature), TSPDT,
  Sight and Sound, Cahiers du cinéma (the 100 and the annual top 10s), House of Tabula's watchlist
  and its cinematic complexity iceberg, each
  browsable in order (`#h/oscar-director`, `#h/cahiers-100`), highlighted on the map and the
  timeline, with your seen count. Film cards carry a badge for every list a film is on; a
  diamond marks such films in a filmography.
- Ratings: every film card shows the TMDB audience rating with its number of votes, and a
  filmography can be sorted by rating.
- Shared crew: once `fetch_tmdb.py` has stored collaborators, a toggle draws links between
  directors who worked with the same cinematographer, editor, composer, writer or designer.

## IMDb ratings, privately

IMDb's licence lets you use its datasets for personal, non-commercial use, but forbids
republishing them, so IMDb ratings are not on the public site. You can still see them
yourself, in your own browser:

- Films you have rated on IMDb: export your ratings on IMDb (Your ratings, Export) and import
  the .csv under "Your films". The export includes the IMDb rating of every film in it.
- Every film: download `title.ratings.tsv`, `title.basics.tsv` and `title.crew.tsv` from
  https://datasets.imdbws.com, then run

      python scripts/imdb_personal.py PATH/title.ratings.tsv PATH/title.basics.tsv PATH/title.crew.tsv

  and import `personal/imdb-ratings.json` under "Your films". With only the ratings file it
  covers the films matched on TMDB; with all three it also covers each director's full
  filmography. Keep that file to yourself: it is IMDb data.

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
