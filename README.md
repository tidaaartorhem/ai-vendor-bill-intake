# InTray — ai-vendor-bill-intake

**The vendor-bill intake desk for "Portside Supply Co.", a fictional Toronto wholesaler.**

## The problem

Every week, hundreds of vendor bills land in the `ap@` inbox as email attachments and pasted text. Someone — usually the most junior person on the finance team — re-keys each one into the accounting system by hand: vendor name, invoice number, date, line items, totals. That manual intake is where the money quietly leaks.

The same vendor arrives under five different spellings ("Harbour Office Supply Inc" vs "Harbour Office Supplies Inc"), so spend reports split one supplier into three and volume discounts go unclaimed. A resent invoice gets paid twice because nobody noticed the invoice number was already posted — and with 82% of real-world invoice numbers appearing more than once (measured below), "already paid" is the norm, not the exception. A vendor splits a $19,000 job into four $4,600–$4,900 invoices on one PO so each slips under the $5,000 director-approval threshold. A header total doesn't foot against its line items and nobody checks. Each of these is a small, boring failure; together they stall the month-end close and bleed cash.

InTray is the intake desk that sits in front of all of that: it captures each arrival, extracts the fields, resolves the vendor alias, dedupes against what's already posted, validates the document, flags split-invoice approval dodges, converts foreign currency, and routes the bill — auto-intake, manager, director, or a review hold with the exact reason. Deterministic throughout: zero LLM calls, every decision traceable to a disclosed rule.

## What this is not

This is the **intake** desk: capture → extract → normalize → dedupe → validate → route. It deliberately stops where [Matchboard (ai-invoice-processing-agent, Oct 11)](https://github.com/tidaaartorhem/ai-invoice-processing-agent) begins — Matchboard covers 2-way/3-way PO matching, GL coding, and early-pay discounts. No overlap: InTray gets the bill *into* the system cleanly; Matchboard decides what happens to it next.

## Pipeline

```
email arrival
    │ intake        stamp replay date, load registers
    ▼
 extract        regex field extraction (invoice#, dates, PO, lines, totals)
    ▼
 normalize      vendor alias → vendor_id (Jaccard ≥ 0.60) · date → ISO ·
                foreign total → CAD via FX table
    ▼
 dedupe         D1 exact / D2 near-duplicate vs posted register
    ▼
 validate       V1 future-dated · V2 unfooted total · V3 missing PO ·
                V4 round-number
    ▼
 split_detect   vendor+PO cluster scan across the replay batch (7-day window)
    ▼
 route          amount tier, or REVIEW with one exact action
    ▼
 draft          human-readable intake note + one-line reasoning
    ▼
 gate           deterministic gate records the routed action
```

Built with LangGraph (`StateGraph`); the rules live in `src/intray/rules.py` as
pure functions with no LangGraph imports, so the TypeScript UI mirror follows
the same logic. The 14 vectors in `data/test-vectors.json` are the shared
contract — Python pytest and TS vitest assert the same expectations.

## Disclosed rules and thresholds

| Rule | Threshold / trigger | Outcome |
|---|---|---|
| Alias | token-set Jaccard ≥ 0.60, tie-break longest canonical name | `vendor_id` or unresolved |
| D1 | same `vendor_id` + `invoice_number` in posted register | `DUPLICATE` → `HOLD_DUPLICATE` |
| D2 | same vendor + total within 1% + date within 7 days + invoice# differs/missing | `LIKELY_DUPLICATE` → `HOLD_DUPLICATE` |
| V1 | `invoice_date` > replay date (2026-11-02) | `V1_FUTURE_DATED` → `SEND_TO_MANAGER` |
| V2 | `|Σ lines + tax − header|` > $0.05 **and** > 0.5% of header | `V2_UNFOOTED_TOTAL` → `CORRECT_TOTAL` (books the true line-sum total) |
| V3 | `po_required` vendor, no PO on the bill | `V3_MISSING_PO` → `REQUEST_PO` |
| V4 | `total_cad` ≥ $1,000 and a whole multiple of $1,000 | `V4_ROUND_NUMBER` → `SEND_TO_MANAGER` (low-weight flag; tier still by amount) |
| SPLIT | same vendor + same PO, invoices in a 7-day window, ≥1 in the $4k–$5k band, cluster sum > $5,000 | `SPLIT_DODGE` → `SEND_TO_DIRECTOR` |
| Tiers | < $1,000 AUTO-INTAKE · $1,000–$5,000 MANAGER · > $5,000 DIRECTOR · any flag → REVIEW | one action per bill |

Flag priority when several fire: duplicate → V2 → V3 → SPLIT_DODGE → V1 → V4 → amount tier.

## Why these rules — measured on real data

Every number below was measured from the UCI Online Retail corpus
(Dec 2010 – Dec 2011, Chen/Clement/Das, CC BY 4.0; `data/raw/Online Retail.xlsx`)
by `scripts/measure_corpus.py`. Full table: `data/README-data.md`.

- **541,909** rows · **24,446** distinct invoice numbers · **20,059 (82.05%)** of invoice numbers appear more than once (including cancelled `C`-prefixed) — this is what motivates the D1 exact-dedupe rule.
- **3,836** cancelled (`C`-prefixed) invoice numbers.
- Lines per invoice: P50 **11.0**, P90 **48.0**. Invoice totals (non-cancelled): P50 **$303.84**, P90 **$940.89** — the bill-total bands ($1k/$5k tiers) sit well above the real P90, so most genuine bills auto-intake.
- **58.58%** of invoices have a line with Quantity > 12; median unit price **$2.08**; busiest month **2011-11** (3,387 invoices).

## The replay feed (seeded — all fictional, disclosed)

`data/outputs/bills.json`: 120 bill arrivals (B001–B120), Oct 26 → Nov 2 2026, replayed Mon 2026-11-02 08:41 EST. 40-vendor register (36 CAD, 2 USD, 1 EUR, 1 GBP; 10 PO-required), 14-bill posted register, seeded FX table (USD 1.41, EUR 1.53, GBP 1.79). Line items are sampled from real corpus tuples; money is integer cents throughout.

Seeded noise, every bill tagged in `seed_flags`: 6 name variants · 4 exact resubmissions (D1) · 4 near-duplicates (D2, one with no invoice-number line) · 4-invoice split cluster (V031, PO-5520, $4,600–$4,900, 5-day window, sum **$19,075**) · 3 missing-PO · 2 unfooted (+$8.38/+0.70%, +$11.68/+0.70%) · 1 future-dated (2026-11-09) · 2 round-number ($2,000/$3,000) · 94 clean. Details: `data/README-data.md`.

## Headline results (from `data/outputs/pipeline-results.json`)

Replay of all 120 arrivals, generated by `scripts/run_intray.py`:

- **32 bills auto-intake ready** (`AUTO_POST`), representing **$16,952.82 CAD** of intake value
- **8 duplicates caught** (3 D1 exact + 5 D2 near-duplicate → all `HOLD_DUPLICATE`)
- **4 split-dodge invoices flagged** (the V031 / PO-5520 cluster, $19,075 → `SEND_TO_DIRECTOR`)
- **3 missing-PO holds** (`REQUEST_PO`), **2 unfooted totals corrected** (`CORRECT_TOTAL`)
- By action: `SEND_TO_MANAGER` 50 · `AUTO_POST` 32 · `SEND_TO_DIRECTOR` 25 · `HOLD_DUPLICATE` 8 · `REQUEST_PO` 3 · `CORRECT_TOTAL` 2
- By tier: MANAGER 47 · AUTO-INTAKE 32 · DIRECTOR 21 · REVIEW 20
- Zero false-positive holds on clean bills: every `HOLD_DUPLICATE`/`REQUEST_PO`/`CORRECT_TOTAL` maps to a seeded-noise bill.

## Eval (from `data/outputs/eval.json`, golden set n=30)

| Metric | Score |
|---|---|
| Extraction — vendor | 1.00 |
| Extraction — invoice number | 0.90 |
| Extraction — invoice date | 1.00 |
| Extraction — total (printed figure) | 1.00 |
| Vendor-alias accuracy | 1.00 |
| Routing accuracy (action vs label) | **1.00** (30/30) |
| Routing precision / recall | 1.00 for every action (AUTO_POST, HOLD_DUPLICATE, REQUEST_PO, CORRECT_TOTAL, SEND_TO_MANAGER, SEND_TO_DIRECTOR) |
| Seeded name-variant resolution | 5/6 (see caveats) |

For the 2 unfooted bills the printed total is wrong by design; extraction is
scored against the printed figure, and the pipeline books the corrected
(true line-sum) total for routing.

## Honest caveats

1. **B005 name variant does not resolve.** The seed README claims all six variants score Jaccard ≥ 0.60; hand-checking shows the author's "2/3 = 0.667" for `Lakeshore Janitorial Supplies` vs `Lakeshore Janitorial Supply` is wrong — the true token-set Jaccard is 2/4 = **0.50**, below the 0.60 bar, so the bill is processed as vendor-unresolved and routed by amount tier (MANAGER, $1,481.77). The other five variants resolve at 0.75 / 0.60 / 0.75 / 0.80 / 0.75.
2. **`INV-` prefix vs golden invoice-number labels.** The vector contract (EXT-02) keeps `INV-` numbers verbatim (`INV-2026-88412`); the golden labels for B010/B012/B025 strip the prefix (`77120`). Extraction follows the vector contract — the 3 extraction "misses" are this labeling difference, not parse errors.
3. **B010 dedupes via D2, not D1.** The bill prints `INV-77120` but the posted register holds `77120`; with the number kept verbatim there is no D1 exact hit. D2 still catches it (same vendor, identical total and date, number differs) → `HOLD_DUPLICATE`. Same action, different match type.
4. **V4 is a low-weight flag by design.** A round $2,000 total is usually legitimate — it only forces a REVIEW-tier `SEND_TO_MANAGER`, never a hold.

## Run it

```bash
pip install -r requirements.txt        # langgraph, pytest, pandas, openpyxl
python scripts/run_intray.py          # writes pipeline-results.json + eval.json
python -m pytest tests/ -q            # 7 tests: 6 vector suites + golden agreement
```

Tests: 6 vector suites covering all 14 hand-computed vectors in
`data/test-vectors.json` (extract ×4, alias ×2, dedupe ×2, validate ×4,
split ×1, route ×1), plus a golden-set agreement test that recomputes eval
metrics from `pipeline-results.json` and asserts they equal the recorded
`eval.json` values — honest by construction.

## Layout

```
src/intray/        rules.py (pure engine) · nodes.py · graph.py
scripts/           run_intray.py · measure_corpus.py · seed_bills.py
tests/             test_intray.py (pytest, reads data/test-vectors.json)
data/              README-data.md · test-vectors.json · golden-set.json
                   outputs/{bills,vendor-register,posted-register,fx-table,
                            corpus-stats,pipeline-results,eval}.json
```

## Links

- Repo: https://github.com/tidaaartorhem/ai-vendor-bill-intake
- Live: https://ai-vendor-bill-intake.web.app
- Companion build (downstream): Matchboard — ai-invoice-processing-agent (PO matching, GL coding, early-pay discounts)
