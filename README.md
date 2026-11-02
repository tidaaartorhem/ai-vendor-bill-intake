# InTray — ai-vendor-bill-intake

Day 6 daily AI workflow build. **InTray** is a vendor-bill intake desk for a
fictional Toronto wholesaler ("Portside Supply Co."): it ingests emailed bill
arrivals, extracts invoice fields, resolves vendor aliases, dedupes against the
posted register, validates (future-dated / unfooted totals / missing PO /
round-number), detects split-invoice approval dodges, converts foreign currency,
and routes each bill to AUTO-INTAKE / MANAGER / DIRECTOR / REVIEW.

## Data

- `data/raw/Online Retail.xlsx` — real UCI Online Retail corpus (Dec 2010–Dec
  2011, Chen/Clement/Das, CC BY 4.0). Line items for the seeded bills are
  sampled from it.
- `data/README-data.md` — measured corpus stats + full disclosure of the
  seeded (fictional) intake feed.
- `data/outputs/` — `vendor-register.json`, `bills.json` (120 arrivals),
  `posted-register.json`, `fx-table.json` (seeded), `corpus-stats.json`.
- `data/test-vectors.json` — 14 hand-computed vectors; the contract the
  Python pipeline and the TS UI both test against.
- `data/golden-set.json` — 30 bills with ground-truth labels for eval.

## Scripts

- `scripts/measure_corpus.py` — measures the real corpus →
  `data/outputs/corpus-stats.json`.
- `scripts/seed_bills.py` — seeds the fictional feed (`random.Random(20261102)`);
  re-running reproduces byte-identical JSON.
