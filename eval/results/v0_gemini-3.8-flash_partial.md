# gemini-3.8-flash baseline (prompt v0), aborted

Run on 2026-10-05 on the free tier, stopped by hand after ~40 minutes.

- 18 of 35 cases attempted. 2 answered by the model (both official cases, both passed),
  16 ended in API errors after retries. 0 wrong answers, 0 substitutions among the answered ones.
- API errors in the log: 54 x 429, 15 x 503 ("model is currently experiencing high demand").
- The 429 message: `Quota exceeded for metric: generate_content_free_tier_requests, limit: 20,
  model: gemini-3.8-flash. Please retry in 10h32m.` The free tier allows 20 requests per day.
- Part of that day's quota had already gone to manual timeout probes and an earlier aborted run
  against the same model, but 20 requests/day is below one 35-case eval run either way.

No `--out` JSON exists because the runner then only wrote results at the end; it now stops
and writes partial results when the quota is exhausted.
