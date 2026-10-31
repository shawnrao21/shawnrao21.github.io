"""Load the Steam CSVs into SQLite, run the analysis, write results as JSON.

The CSVs do not parse with pandas (unescaped commas) and two of the six tables
are localised per game, so the loader reads through the stdlib csv module and
the schema only keeps the columns that are reliably English.
"""
import csv, json, math, sqlite3, sys

RAW = "data/raw/"
DB = "data/steam.db"
OUT = sys.argv[1]

con = sqlite3.connect(DB)
con.executescript("""
DROP TABLE IF EXISTS games;  DROP TABLE IF EXISTS reviews;
DROP TABLE IF EXISTS spy;    DROP TABLE IF EXISTS tags;
CREATE TABLE games  (app_id INTEGER PRIMARY KEY, name TEXT, released TEXT, type TEXT);
CREATE TABLE reviews(app_id INTEGER PRIMARY KEY, positive INT, negative INT, total INT, metacritic INT);
CREATE TABLE spy    (app_id INTEGER PRIMARY KEY, developer TEXT, publisher TEXT,
                     owners TEXT, price INT, genres TEXT, languages TEXT);
CREATE TABLE tags   (app_id INTEGER, tag TEXT);
""")


def rows(name, cols, tail=()):
    """cols read from the left, tail from the right. rows carry extra fields
    where a quoted value contained a comma, so a fixed middle index is unsafe."""
    with open(RAW + name, encoding="utf-8", errors="replace", newline="") as fh:
        r = csv.reader(fh)
        hdr = next(r)
        idx = [hdr.index(c) for c in cols]
        tidx = [hdr.index(c) - len(hdr) for c in tail]
        need = max(idx) if idx else 0
        for row in r:
            if len(row) <= need or len(row) < len(hdr):
                continue
            yield [row[i] for i in idx] + [row[i] for i in tidx]


def ints(vals, which):
    out = list(vals)
    for i in which:
        try:
            out[i] = int(float(out[i]))
        except Exception:
            out[i] = None
    return out


print("loading into sqlite:")
g = [ints(r, [0]) for r in rows("games.csv", ["app_id", "name", "release_date"], ["type"])]
con.executemany("INSERT OR IGNORE INTO games VALUES (?,?,?,?)", g)
print(f"  games   {len(g):>7,}")

v = [ints(r, [0, 1, 2, 3, 4]) for r in
     rows("reviews.csv", ["app_id", "positive", "negative", "total", "metacritic_score"])]
con.executemany("INSERT OR IGNORE INTO reviews VALUES (?,?,?,?,?)", v)
print(f"  reviews {len(v):>7,}")

s = [ints(r, [0, 4]) for r in rows("steamspy_insights.csv",
     ["app_id", "developer", "publisher", "owners_range", "price", "genres", "languages"])]
con.executemany("INSERT OR IGNORE INTO spy VALUES (?,?,?,?,?,?,?)", s)
print(f"  spy     {len(s):>7,}")

t = [ints(r, [0]) for r in rows("tags.csv", ["app_id", "tag"])]
con.executemany("INSERT INTO tags VALUES (?,?)", t)
print(f"  tags    {len(t):>7,}")

con.executescript("CREATE INDEX idx_tag ON tags(tag); CREATE INDEX idx_tag_app ON tags(app_id);")
con.commit()

# Wilson lower bound as a SQL function, so ranking happens in the query
con.create_function("wilson", 2, lambda p, n: 0.0 if not n else (
    (p / n + 1.96 ** 2 / (2 * n) -
     1.96 * math.sqrt((p / n * (1 - p / n) + 1.96 ** 2 / (4 * n)) / n)) /
    (1 + 1.96 ** 2 / n)))

BASE = """
  WITH rated AS (
    SELECT g.app_id, g.name, s.developer, s.price / 100.0 AS usd,
           CAST(substr(g.released, 1, 4) AS INT) AS yr,
           r.total, wilson(r.positive, r.total) AS score, s.genres, s.languages
    FROM games g
    JOIN reviews r ON r.app_id = g.app_id
    JOIN spy     s ON s.app_id = g.app_id
    WHERE g.type = 'game' AND r.total >= 150
  )
"""

QUERIES = [
    ("Does a higher price buy a better game?",
     "Grouping every rated game into price bands and taking the mean Wilson score of each.",
     BASE + """
     SELECT CASE WHEN usd = 0 THEN 'Free'
                 WHEN usd < 10 THEN 'Under $10'
                 WHEN usd < 20 THEN '$10 to $20'
                 WHEN usd < 40 THEN '$20 to $40'
                 ELSE '$40 and up' END AS band,
            COUNT(*) AS games,
            ROUND(AVG(score) * 100, 1) AS avg_score
     FROM rated GROUP BY band ORDER BY MIN(usd);"""),

    ("Which genres hold up best?",
     "The genres column holds a comma-separated list, so it is split with a recursive CTE before grouping.",
     BASE + """,
     split(app_id, score, genre, rest) AS (
       SELECT app_id, score, '', genres || ',' FROM rated WHERE genres IS NOT NULL
       UNION ALL
       SELECT app_id, score,
              TRIM(substr(rest, 1, instr(rest, ',') - 1)),
              substr(rest, instr(rest, ',') + 1)
       FROM split WHERE rest <> ''
     )
     SELECT genre, COUNT(*) AS games, ROUND(AVG(score) * 100, 1) AS avg_score
     FROM split WHERE genre <> '' AND genre <> '\\N' GROUP BY genre
     HAVING COUNT(*) >= 80 ORDER BY avg_score DESC LIMIT 8;"""),

    ("Are studios that ship more games better at it?",
     "Developers with at least five rated releases, ranked by their average score.",
     BASE + """
     SELECT developer, COUNT(*) AS games,
            ROUND(AVG(score) * 100, 1) AS avg_score,
            SUM(total) AS reviews
     FROM rated WHERE developer IS NOT NULL AND developer <> ''
     GROUP BY developer HAVING COUNT(*) >= 5
     ORDER BY avg_score DESC LIMIT 8;"""),

    ("Does shipping in more languages track with reception?",
     "Counting commas in the languages field as a proxy for how many locales a game ships in.",
     BASE + """
     SELECT CASE WHEN n <= 1 THEN 'English only'
                 WHEN n <= 5 THEN '2 to 5'
                 WHEN n <= 15 THEN '6 to 15'
                 ELSE 'over 15' END AS locales,
            COUNT(*) AS games, ROUND(AVG(score) * 100, 1) AS avg_score
     FROM (SELECT score,
                  LENGTH(languages) - LENGTH(REPLACE(languages, ',', '')) + 1 AS n
           FROM rated WHERE languages IS NOT NULL AND languages <> '')
     GROUP BY locales ORDER BY MIN(n);"""),

    ("What do the best-reviewed co-op games have in common?",
     "Joining to the tag table, then counting which other tags appear most on highly rated co-op games.",
     BASE + """
     SELECT t.tag, COUNT(*) AS games, ROUND(AVG(rt.score) * 100, 1) AS avg_score
     FROM rated rt
     JOIN tags t  ON t.app_id = rt.app_id
     WHERE rt.app_id IN (SELECT app_id FROM tags WHERE tag = 'Co-op')
       AND rt.score > 0.85 AND t.tag <> 'Co-op'
     GROUP BY t.tag HAVING COUNT(*) >= 25
     ORDER BY games DESC LIMIT 8;"""),

    ("Has Steam got better or worse since 2010?",
     "Mean score by release year, with a window function carrying the three-year rolling average.",
     BASE + """
     SELECT yr AS year, COUNT(*) AS games,
            ROUND(AVG(score) * 100, 1) AS avg_score,
            ROUND(AVG(AVG(score)) OVER (ORDER BY yr ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) * 100, 1) AS rolling_3yr
     FROM rated WHERE yr BETWEEN 2010 AND 2024
     GROUP BY yr ORDER BY yr;"""),
]

out = []
print("\nrunning queries:")
for title, note, sql in QUERIES:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    data = [list(r) for r in cur.fetchall()]
    out.append({"title": title, "note": note,
                "sql": "\n".join(l for l in sql.strip().splitlines()),
                "cols": cols, "rows": data})
    print(f"  {title[:52]:54} {len(data):>3} rows")

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(out, fh, separators=(",", ":"))
print(f"\nwrote {OUT}")
con.close()
