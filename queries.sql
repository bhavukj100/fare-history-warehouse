-- Current fares. Money uses integer cents to avoid binary floating-point drift.
SELECT route, airline, fare_cents, currency FROM fare_history WHERE valid_to IS NULL;
-- Version timeline with price changes using a SQL window function.
SELECT route, airline, valid_from, fare_cents,
       fare_cents - LAG(fare_cents) OVER (PARTITION BY route, airline ORDER BY valid_from) AS change_cents
FROM fare_history ORDER BY route, airline, valid_from;
-- Half-open validity intervals make an exact boundary belong to the new version.
SELECT * FROM fare_history
WHERE valid_from <= '2026-01-02T00:00:00+00:00'
  AND (valid_to > '2026-01-02T00:00:00+00:00' OR valid_to IS NULL);
