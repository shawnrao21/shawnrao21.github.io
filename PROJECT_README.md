# Long-Distance Co-op

Pick who is playing, a price ceiling and some genres, and it ranks 3,000 Steam
games. Or name a game you already liked and it finds the closest matches.

**Live:** https://shawnrao21.github.io/games.html

Everything runs in the browser. No server, no API keys, no backend to pay for.

---

## Why this exists

My friends and I kept having the same conversation about what to play, and
Steam's own search is built for browsing a store rather than settling an
argument between four people with different libraries and a price ceiling.

## What it does

| | |
| --- | --- |
| **Filter** | player mode (co-op, PvP, split screen, MMO, solo), price cap, genre |
| **Rank** | Wilson lower bound on the positive review ratio |
| **Recommend** | cosine similarity over IDF-weighted tag vectors |
| **Analyse** | six SQL queries and two regressions, shown with their output |

---

## Stack and why

| Layer | Tool | Why |
| --- | --- | --- |
| Pipeline | Python, pandas | six CSVs, 3.04M rows, to one 199KB gzipped JSON |
| Queries | SQLite | the aggregate questions are plainly SQL |
| Statistics | R (`lm`) | testing whether the SQL findings survive controls |
| Front end | vanilla JS | no framework needed for one page |

```
build_coop.py     CSVs  -> data/coop.json    (what the browser loads)
build_sql.py      CSVs  -> steam.db + data/analysis.json
analysis.R        steam.db -> the regressions
games.html        the tool
```

---

## Ranking: why not just the positive percentage

A raw ratio ranks five reviews out of five above 48,000 out of 50,000. Both
are "100%" and "96%", and only one of them is evidence.

I use the lower bound of a Wilson score interval instead, which asks what the
floor on the true positive rate is given the sample size:

```
         p + z²/2n  -  z · sqrt((p(1-p) + z²/4n) / n)
score =  ------------------------------------------------
                        1 + z²/n
```

Small samples get pulled toward the middle. Large samples barely move. Games
need 150 reviews to appear at all.

## Recommendations: why tag rarity matters

Each game is a vector over its eight rarest tags, each weighted by
`log(N / games_with_tag)`. Similarity is the cosine between two vectors.

Without the weighting, almost every pair of games looks similar, because
nearly everything on Steam is tagged Action or Indie. Weighting by rarity
means "Open World Survival Craft" counts for far more than "Action" does.

Spot checks:

| Input | Returns |
| --- | --- |
| Terraria | Starbound, Edge of Space, Volcanoids |
| Hades | Hades II, Noita, The Binding of Isaac |

---

## The data, and what was wrong with it

Source: [steam-insights](https://github.com/NewbieIndieGameDev/steam-insights),
a public snapshot of the Steam store and SteamSpy. Six CSVs, 3,040,866 rows.

Cleaning took longer than building. Four problems, each of which produced a
plausible-looking wrong answer rather than an error:

**1. pandas silently dropped 54% of one file.**
`games.csv` has unescaped commas inside quoted fields. `read_csv` skipped the
malformed rows and reported nothing. The stdlib `csv` module parses all 140,082
correctly.

**2. A column index landed in the wrong field.**
Rows with extra fields pushed `type` off position 6, so filtering on
`type == 'game'` was selecting near-random rows. It is the last column, so it
has to be read from the right, not the left.

**3. Playtime was zero for all 140,077 rows.**
SteamSpy stopped publishing it. I had built an hours-per-dollar metric on top
of it before checking the distribution. Cut the feature.

**4. The join tables are localised per game.**
`categories.csv` stores Counter-Strike in Polish, Dota in Russian, Terraria in
Russian. Filtering to English deleted the biggest games on Steam. SteamSpy's
`genres` column and `tags.csv` are fully English, so the multiplayer flags come
from tags instead.

A fifth, less obvious: sorting by owner count to pick the top games returned an
almost entirely free-to-play set, because the largest libraries on Steam are
Dota, CS2 and Apex. Review count is the better proxy for "games people have
actually played".

---

## Testing the findings

The SQL turned up two results worth a second look.

**Price.** Scores peak at $10 to $20 (78.5%) and fall off above $40 (75.1%).
The F test is emphatic, F = 45.8, p < 0.001. It also explains an R² of 0.0103.
Price accounts for about 1% of why one game reviews better than another.
Significant and useful are different questions.

**Localisation.** Games in more than 15 languages average 4.86 points higher,
t = 11.21, n = 17,687. That looks like a real effect until you notice
publishers localise games that already sold: localised games here carry a
median 1,299 reviews against 552.

Put review count, release year, price and indie status into the model:

| term | β (points) | std err | t | p |
| --- | --- | --- | --- | --- |
| many_locales | +1.31 | 0.49 | 2.67 | 0.008 |
| log_reviews | +3.35 | 0.08 | 43.77 | <0.001 |
| year | +0.66 | 0.03 | 21.98 | <0.001 |
| log_price | +0.49 | 0.10 | 4.77 | <0.001 |
| indie | +2.90 | 0.23 | 12.36 | <0.001 |

R² goes from 0.005 to 0.130. The localisation coefficient drops from 4.86 to
1.31, so 73% of the apparent effect was the confounder. What is left is real
and about a quarter the size of the headline.

---

## Running it

`analysis.R` needs nothing but R. The dataset it reads,
`data/steam_model.csv`, ships with the repo.

```sh
Rscript analysis.R          # run from the repo root, not from inside data/
python3 -m http.server 8000 # then open localhost:8000/games.html
```

Rebuilding the datasets from the raw CSVs, which are too large for the repo,
needs the source archive linked above:

```sh
pip install pandas statsmodels
python build_coop.py data/coop.json     # browser dataset
python build_sql.py  data/analysis.json # steam.db, query output, steam_model.csv
```

The page fetches its data, so it needs a server. Opening `games.html` from a
`file://` path will fail on the fetch.

---

## Known limits

- The data is a snapshot, not live. Prices and review counts drift.
- 3,000 games is the top slice by review count, so niche titles are missing.
- Tag similarity has no notion of quality. It will happily recommend a badly
  reviewed game that shares tags, which is why the filters and the ranking are
  separate from the recommender.
- Steam is a trademark of Valve. Independent student project, not affiliated
  with or endorsed by Valve.
