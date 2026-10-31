# Does localisation actually make a game better reviewed?
#
# The SQL on the Game Finder page found that games shipping in more than 15
# languages average 81.3% positive against 76.2% for English-only ones. Five
# points is a lot. This checks whether that gap survives controlling for the
# obvious confounder: publishers localise games that have already sold well.
#
# Run from the repo root, with steam.db built by build_sql.py:
#   Rscript analysis.R

library(DBI)
library(RSQLite)

con <- dbConnect(SQLite(), "data/steam.db")

raw <- dbGetQuery(con, "
  SELECT g.app_id, g.name, s.price/100.0 AS usd,
         CAST(substr(g.released,1,4) AS INT) AS yr,
         r.positive, r.total, s.languages, s.genres
  FROM games g
  JOIN reviews r ON r.app_id = g.app_id
  JOIN spy     s ON s.app_id = g.app_id
  WHERE g.type = 'game' AND r.total >= 150
    AND s.languages IS NOT NULL AND s.languages <> ''
")

dbDisconnect(con)

# Wilson lower bound. A raw positive percentage lets 5 reviews out of 5 beat
# 48,000 out of 50,000, which is not what anyone means by "better reviewed".
wilson <- function(pos, n, z = 1.96) {
  ph <- pos / n
  (ph + z^2 / (2 * n) - z * sqrt((ph * (1 - ph) + z^2 / (4 * n)) / n)) / (1 + z^2 / n)
}

d <- within(raw, {
  score        <- wilson(positive, total)
  locales      <- lengths(regmatches(languages, gregexpr(",", languages))) + 1
  many_locales <- as.integer(locales > 15)
  log_reviews  <- log(total)
  log_price    <- log1p(usd)
  indie        <- as.integer(grepl("Indie", genres))
})

d <- subset(d, yr >= 2006 & yr <= 2024 & is.finite(score) & is.finite(log_reviews))
cat("n =", nrow(d), "\n\n")

# ---- 1. the gap as the SQL reported it ------------------------------------
many <- d$score[d$many_locales == 1]
few  <- d$score[d$many_locales == 0]

cat("many locales:", round(mean(many) * 100, 2), "%  n =", length(many), "\n")
cat("few locales :", round(mean(few) * 100, 2), "%  n =", length(few), "\n")
print(t.test(many, few))

# Cohen's d, because a p value this small only says the gap is not zero.
pooled <- sqrt(((length(many) - 1) * var(many) + (length(few) - 1) * var(few)) /
               (length(many) + length(few) - 2))
cat("Cohen's d =", round((mean(many) - mean(few)) / pooled, 3), "\n\n")

# ---- 2. localisation on its own -------------------------------------------
m1 <- lm(score ~ many_locales, data = d)
cat("--- model 1: localisation alone ---\n")
print(summary(m1))

# ---- 3. the same, controlling for how many people reviewed it -------------
m2 <- lm(score ~ many_locales + log_reviews + yr + log_price + indie, data = d)
cat("--- model 2: controlling for popularity, age, price, indie ---\n")
print(summary(m2))

shrink <- (1 - coef(m2)["many_locales"] / coef(m1)["many_locales"]) * 100
cat("\nthe localisation coefficient shrinks", round(shrink, 1),
    "% once popularity is in the model\n")

# ---- 4. the confounder, stated plainly ------------------------------------
cat("median reviews, many locales:", median(d$total[d$many_locales == 1]), "\n")
cat("median reviews, few locales :", median(d$total[d$many_locales == 0]), "\n")
cat("cor(locales, log reviews)   :",
    round(cor(d$locales, d$log_reviews), 3), "\n\n")

# ---- 5. and the price finding, same treatment -----------------------------
d$band <- cut(d$usd, c(-1, 0, 10, 20, 40, 1000),
              labels = c("Free", "Under $10", "$10-20", "$20-40", "$40+"))
print(aggregate(score ~ band, d, function(x) round(mean(x) * 100, 1)))
mb <- lm(score ~ band, data = d)
cat("\nprice bands explain R^2 =", round(summary(mb)$r.squared, 4),
    "of the variance in score\n")
print(anova(mb))

# A significant F with an R^2 of 0.01 means the bands differ, and that the
# difference is worth almost nothing for predicting whether you will like a
# game. Those are different questions and the p value only answers the first.
