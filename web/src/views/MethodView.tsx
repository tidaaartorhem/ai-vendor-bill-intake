import type { IntakeData } from "../data";
import { SectionTitle } from "./shared";

const RULES: Array<[string, string]> = [
  ["Capture", "Bills arrive as document text (vendor line, invoice number, date, optional PO, currency, line items, subtotal / tax / total)."],
  ["Extract", "Ordered regexes: Invoice # → INV- → No.; dates in “Oct 28 2026”, “28/10/2026”, “2026-10-28” → ISO; PO-#### refs; “qty × description @ $price” line rows; subtotal / tax / total."],
  ["Normalize", "Vendor alias resolution by token-set Jaccard ≥ 0.60 against the 40-vendor register; ties break to the longest canonical name. Foreign totals → CAD at the seeded FX table (USD 1.41, EUR 1.53, GBP 1.79)."],
  ["Dedupe", "D1 exact: same vendor + invoice number as a posted bill → DUPLICATE. D2 near: same vendor, total within 1%, invoice date within 7 days, invoice number differs → LIKELY_DUPLICATE. Both hold the bill (HOLD_DUPLICATE)."],
  ["Validate", "V1 future-dated (invoice date after the 2026-11-02 replay). V2 unfooted (header total vs true line total differs by > $0.05 AND > 0.5% → CORRECT_TOTAL). V3 missing PO for PO-required vendors → REQUEST_PO. V4 round-number total ≥ $1,000 → low-weight informational flag, routing follows the tier."],
  ["Split-dodge", "Same vendor + same PO inside a 7-day window, any invoice in the $4,000–$5,000 band, cluster sum above $5,000 → routed to the director."],
  ["Route", "Clean bills by total: < $1,000 AUTO-INTAKE (auto-post), $1,000–$5,000 MANAGER, > $5,000 DIRECTOR. Any duplicate or validation flag forces review instead of the tier."],
];

function num(v: unknown): string {
  if (typeof v === "number") return v.toLocaleString("en-US");
  return String(v ?? "—");
}

export default function MethodView({ data }: { data: IntakeData }) {
  const s = data.corpusStats;
  // Flatten one level so nested score objects (e.g. extraction_accuracy)
  // still show as readable scalars; the full file sits in <details> below.
  const evalEntries: Array<[string, string]> = [];
  if (data.eval) {
    for (const [k, v] of Object.entries(data.eval)) {
      if (typeof v === "number" || typeof v === "string" || typeof v === "boolean") {
        evalEntries.push([k, String(v)]);
      } else if (v != null && typeof v === "object" && !Array.isArray(v)) {
        for (const [sk, sv] of Object.entries(v as Record<string, unknown>)) {
          if (typeof sv === "number" || typeof sv === "string" || typeof sv === "boolean") {
            evalEntries.push([`${k}.${sk}`, String(sv)]);
          }
        }
      }
    }
  }

  return (
    <div>
      <SectionTitle
        title="Methodology"
        sub="What InTray is, the exact deterministic rules it runs, the real corpus measurements behind them, and what in this batch is seeded."
      />

      <h3 className="group-title">What this is — and is not</h3>
      <p>
        InTray is the <strong>intake desk</strong> for Portside Supply Co., a
        Toronto wholesaler: capture → extract → normalize → dedupe → route.
        It is <strong>not</strong> PO matching and <strong>not</strong> GL
        coding — it decides what each incoming vendor bill is, whether it has
        been seen before, and who should approve it. Nothing posts to the
        ledger until a human approves.
      </p>

      <h3 className="group-title">The rules</h3>
      <dl className="rules">
        {RULES.map(([name, text]) => (
          <div key={name}>
            <dt>{name}</dt>
            <dd>{text}</dd>
          </div>
        ))}
      </dl>

      <h3 className="group-title">Real corpus measurements</h3>
      <p className="muted">
        Measured from the UCI Online Retail corpus (Dec 2010 – Dec 2011, Chen
        / Clement / Das, CC BY 4.0) by scripts/measure_corpus.py. These
        numbers motivated the rules — nothing here is estimated.
      </p>
      <dl className="kv stats">
        <div><dt>Raw rows</dt><dd className="mono">{num(s.raw_rows)}</dd></div>
        <div><dt>Distinct InvoiceNo</dt><dd className="mono">{num(s.total_invoices_distinct_invoiceno)}</dd></div>
        <div><dt>InvoiceNo values duplicated</dt><dd className="mono">{num(s.duplicate_invoice_numbers)} ({((s.duplicate_invoice_rate as number) * 100).toFixed(2)}%)</dd></div>
        <div><dt>…of which cancelled (C-prefixed)</dt><dd className="mono">{num(s.cancelled_invoice_numbers_c_prefixed)}</dd></div>
        <div><dt>Why it matters</dt><dd>An 82.05% duplicate-InvoiceNo rate is what motivates the D1 exact-dedupe rule.</dd></div>
        <div><dt>Lines per invoice — P50 / P90</dt><dd className="mono">{num(s.lines_per_invoice_p50)} / {num(s.lines_per_invoice_p90)}</dd></div>
        <div><dt>Invoice total, non-cancelled — P50 / P90</dt><dd className="mono">${num(s.invoice_total_non_cancelled_p50)} / ${num(s.invoice_total_non_cancelled_p90)}</dd></div>
        <div><dt>Invoices with any line Quantity &gt; 12</dt><dd className="mono">{(((s.share_invoices_any_line_qty_gt_12 as number) ?? 0) * 100).toFixed(2)}%</dd></div>
        <div><dt>Median unit price</dt><dd className="mono">${num(s.median_unit_price)}</dd></div>
        <div><dt>Busiest month</dt><dd className="mono">{String(s.busiest_month ?? "—")} ({num((s.invoices_per_month as Record<string, number> | undefined)?.["2011-11"])} invoices)</dd></div>
      </dl>

      <h3 className="group-title">Seeded batch (disclosed)</h3>
      <ul className="notes">
        <li>120 bills, received Oct 26 – Nov 2 2026; replay Mon 2026-11-02 08:41 EST.</li>
        <li>40-vendor register: 36 CAD, 2 USD, 1 EUR, 1 GBP; 10 vendors PO-required; FX table seeded (USD 1.41, EUR 1.53, GBP 1.79 → CAD).</li>
        <li>Seeded noise: 6 name variants · 4 exact + 4 near-duplicate resubmissions · 4-invoice split cluster (V031 / PO-5520, $4.6k–$4.9k each, sum $19,075) · 3 missing-PO · 2 unfooted totals · 1 future-dated (2026-11-09) · 2 round-number ($2,000 / $3,000) · 94 clean.</li>
        <li>14-bill posted register: the originals of all 8 resubmissions plus 6 filler posted bills.</li>
        <li>Line items sample real corpus (Description, Quantity, UnitPrice) tuples; bill totals were anchored on the measured invoice-total P50 ($303.84) / P90 ($940.89).</li>
      </ul>

      <h3 className="group-title">Golden-set evaluation</h3>
      {data.eval == null ? (
        <p className="note">Eval pending — the engine has not written eval.json yet.</p>
      ) : (
        <div>
          {evalEntries.length > 0 && (
            <dl className="kv stats">
              {evalEntries.map(([k, v]) => (
                <div key={k}>
                  <dt className="mono">{k}</dt>
                  <dd className="mono">{v}</dd>
                </div>
              ))}
            </dl>
          )}
          <details>
            <summary className="muted">Raw eval.json</summary>
            <pre className="raw-json">{JSON.stringify(data.eval, null, 2)}</pre>
          </details>
        </div>
      )}
      <p className="muted">
        The golden set holds 30 hand-labeled bills (6 clean auto-posts, 3
        manager-tier, 1 director-tier, 8 duplicates, 4 split-cluster, 3
        missing-PO, 2 unfooted, 1 future-dated, 2 round-number).
      </p>
    </div>
  );
}
