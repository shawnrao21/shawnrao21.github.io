"""Build the co-op dataset: which games a group spread across cities can
actually play together, and on what terms.

The old build collapsed everything into one "coop" flag, which is wrong for
this question. "Co-op" on Steam covers three things that are not
interchangeable when your friends are not in the room:

  Online Co-op                you each own it, you play over the internet
  Shared/Split Screen Co-op   same couch, same TV. useless at a distance
  LAN Co-op                   same network. also useless at a distance
  Remote Play Together        ONE person owns it and streams it to the others

That last one matters most and is the least known. It turns a couch game into
an online one and only one copy gets bought.

Categories carry those distinctions; tags do not. The catch is that
categories.csv is localised per game, and it is the biggest titles that are
affected (CS2 in Polish, Dota and Apex in Russian). So: read categories, map
the non-English strings for the phrases that matter, and where a game's
co-op mode still cannot be established, fall back to tags and mark it as a
coarse guess rather than pretending to know.
"""
import csv, json, math, sys, collections

RAW = "data/raw/"
OUT = sys.argv[1] if len(sys.argv) > 1 else "data/coop.json"

def rows(name, cols, tail=()):
    """Read by column name. Trailing columns are indexed from the right: some
    rows carry extra fields from unescaped commas, so a fixed index into the
    middle of a row lands on the wrong value."""
    with open(RAW + name, encoding="utf-8", errors="replace", newline="") as fh:
        r = csv.reader(fh); hdr = next(r)
        idx = {c: hdr.index(c) for c in cols}
        tidx = {c: hdr.index(c) - len(hdr) for c in tail}
        need = max(idx.values()) if idx else 0
        out = []
        for row in r:
            if len(row) <= need or len(row) < len(hdr):
                continue
            rec = {c: row[i] for c, i in idx.items()}
            rec.update({c: row[i] for c, i in tidx.items()})
            out.append(rec)
    print(f"  {name:24} {len(out):>7,}")
    return out

# ---- the category phrases that decide whether a group can play together ----
# only phrases confirmed present in this dataset are listed. anything not
# listed stays unmapped on purpose: a wrong flag is worse than a missing one.
CAT = {}
def mark(flag, *names):
    for n in names: CAT[n] = flag

mark("online",
     "Online Co-op", "Кооператив (по сети)", "Coopération en ligne",
     "Cooperativo en línea", "Cooperativos en línea", "在线合作", "線上合作",
     "オンライン協力プレイ", "Verkkoyhteistyöpeli")
mark("coop",                     # co-op, mode unstated
     "Co-op", "Кооператив", "Coopération", "合作", "協力プレイ", "Yhteistyöpeli")
mark("couch",                    # same room only
     "Shared/Split Screen Co-op", "Shared/Split Screen",
     "Кооператив (общий/разделённый экран)", "Общий/разделённый экран",
     "Coop locale et écran partagé", "同屏/分屏合作", "同屏/分屏",
     "Jaetun näytön yhteistyöpeli", "Jaettu näyttö")
mark("lan",
     "LAN Co-op", "LAN – co-op", "Кооператив (локальная сеть)", "局域网合作")
mark("rpt",                      # one copy, streamed to the others
     "Remote Play Together", "远程同乐")
mark("xplat",
     "Cross-Platform Multiplayer", "Кросс-платформенный мультиплеер",
     "跨平台多人", "Wieloplatformowa wieloosobowa",
     "Plattformübergreifender Mehrspieler")
mark("multi",
     "Multi-player", "Для нескольких игроков", "多人", "マルチプレイヤー",
     "Wieloosobowa")
mark("mmo", "MMO", "大型多人線上")
mark("pad",
     "Full controller support", "Полная поддержка контроллеров",
     "Повна підтримка контролерів", "完全支持控制器", "完全支援控制器",
     "フルコントローラサポート", "Volle Controllerunterstützung",
     "Compat. contrôleurs complète", "Pełna obsługa kontrolerów",
     "Plná podpora ovladačů", "Fuld controllerunderstøttelse",
     "Täysi tuki ohjaimille")
mark("family",
     "Family Sharing", "Семейный доступ", "Сімейна бібліотека",
     "Préstamo familiar", "Compartilhamento em família", "家庭共享",
     "ファミリーシェアリング", "Udostępnianie gier", "Sdílení v rodině")

def wilson(pos, tot, z=1.96):
    """Lower bound on the true positive rate. A raw ratio says 5/5 beats
    48000/50000, which is not what anyone means by 'better reviewed'."""
    if tot <= 0: return 0.0
    p = pos / tot
    d = 1 + z * z / tot
    centre = p + z * z / (2 * tot)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * tot)) / tot)
    return (centre - margin) / d

def owners_mid(s):
    try:
        lo, hi = [int(x.strip().replace(",", "")) for x in str(s).split("..")]
        return (lo + hi) // 2
    except Exception:
        return 0

def n(v, d=0.0):
    try:
        if v in ("", "\\N", None): return d
        return float(v)
    except Exception:
        return d

print("loading:")
games = {r["app_id"]: r for r in rows("games.csv", ["app_id", "name", "release_date"], tail=["type"])
         if r["type"] == "game"}
rev   = {r["app_id"]: r for r in rows("reviews.csv", ["app_id", "positive", "total"])}
spy   = {r["app_id"]: r for r in rows("steamspy_insights.csv",
         ["app_id", "developer", "owners_range", "price", "initial_price", "discount", "genres"])}

cats = collections.defaultdict(set)
for r in rows("categories.csv", ["app_id", "category"]):
    f = CAT.get(r["category"])
    if f: cats[r["app_id"]].add(f)

tagrows = rows("tags.csv", ["app_id", "tag"])
tags = collections.defaultdict(list)
for r in tagrows: tags[r["app_id"]].append(r["tag"])
tagfreq = collections.Counter(r["tag"] for r in tagrows)

TAG_COOP  = {"Co-op", "Online Co-Op", "Co-op Campaign", "Multiplayer"}
TAG_COUCH = {"Local Co-Op", "Split Screen", "Local Multiplayer"}

out, counts = [], collections.Counter()
for aid, g in games.items():
    rv, sp = rev.get(aid), spy.get(aid)
    if not rv or not sp: continue
    total = n(rv["total"]); 
    if total < 150: continue              # too few reviews for a rating to mean anything
    c = cats.get(aid, set())
    t = set(tags.get(aid, []))

    online = "online" in c
    rpt    = "rpt" in c
    couch  = "couch" in c
    lan    = "lan" in c
    anycoop = online or couch or lan or ("coop" in c)

    # how confident are we about the MODE, as opposed to just "has co-op"
    if c:
        src = "cat"
    elif t & (TAG_COOP | TAG_COUCH):
        src = "tag"
        anycoop = True
        couch = couch or bool(t & TAG_COUCH)
        online = online or bool(t & {"Online Co-Op"})
    else:
        src = "none"

    if not (anycoop or rpt): continue     # not a co-op game at all
    # playable apart? online co-op, or one person streams it with Remote Play
    together = online or rpt
    if not together and src == "tag":
        together = None                   # unknown, not false: say so rather than guess
    counts[src] += 1

    price = n(sp["price"]) / 100.0
    init  = n(sp["initial_price"]) / 100.0
    disc  = n(sp["discount"])
    gen = [x.strip() for x in str(sp["genres"]).split(",") if x.strip() and x.strip() != "\\N"][:4]
    kw = sorted(tags.get(aid, []), key=lambda x: tagfreq[x])[:8]
    yr = None
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%d %b, %Y"):
        try:
            import datetime; yr = datetime.datetime.strptime(g["release_date"], fmt).year; break
        except Exception: pass

    out.append({
        "i": int(aid), "n": g["name"], "y": yr,
        "p": round(price, 2), "ip": round(init, 2), "dc": int(disc),
        "s": round(wilson(n(rv["positive"]), total), 4),
        "t": int(total), "o": owners_mid(sp["owners_range"]), "d": sp["developer"],
        "on": online, "rpt": rpt, "couch": couch, "lan": lan,
        "xp": "xplat" in c, "pad": "pad" in c, "fam": "family" in c,
        "mmo": "mmo" in c, "tog": together, "src": src,
        "g": gen, "k": kw,
    })

out.sort(key=lambda r: -r["t"])
out = out[:3000]
print(f"\nco-op games kept: {len(out)}")
print("  mode established from categories:", counts["cat"], " from tags only:", counts["tag"])
for k in ("on", "rpt", "couch", "lan", "xp", "fam", "pad"):
    print(f"  {k:6} {sum(1 for r in out if r[k]):>5}")
print("  playable apart:", sum(1 for r in out if r["tog"] is True),
      " couch-only:", sum(1 for r in out if r["tog"] is False),
      " unknown:", sum(1 for r in out if r["tog"] is None))
print("  free:", sum(1 for r in out if r["p"] == 0),
      " on sale now:", sum(1 for r in out if r["dc"] > 0))

import datetime
json.dump({"generated": datetime.date.today().isoformat(), "count": len(out), "games": out},
          open(OUT, "w"), separators=(",", ":"))
print("wrote", OUT)
