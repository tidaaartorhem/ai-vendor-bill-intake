import type { IntakeData } from "../data";
import { ActionChip, FlagChip, SectionTitle, fmtMoney } from "./shared";
import type { PipelineBill } from "../rules";

function dupExplanation(b: PipelineBill): string {
  const d = b.detail.dedupe as any;
  if (d?.match_type === "D1_EXACT") {
    const m = d.matched_posted ?? {};
    return `D1 exact: same vendor (${m.vendor_id}) and invoice number (${m.invoice_number}) as an already-posted bill. Held for review.`;
  }
  return (
    `D2 near-duplicate: same vendor, total differs by ${d?.total_diff_pct ?? "?"}% ` +
    `(within 1%) and invoice date by ${d?.date_diff_days ?? "?"} days (within 7), ` +
    `but the invoice number differs. Held for review.`
  );
}

function validationExplanation(b: PipelineBill, flag: string): string {
  switch (flag) {
    case "V1_FUTURE_DATED": {
      const v1 = b.detail.v1 as any;
      return `V1: invoice date ${b.invoice_date} is ${v1?.days_after_replay ?? "?"} day(s) after the replay date 2026-11-02. A bill cannot be dated in the future.`;
    }
    case "V2_UNFOOTED_TOTAL": {
      const v2 = b.detail.v2 as any;
      return `V2: printed header total ${fmtMoney(v2?.header_total ?? 0)} does not foot — the true line total is ${fmtMoney(v2?.corrected_total ?? 0)} (diff ${fmtMoney(v2?.diff ?? 0)}, ${v2?.diff_pct ?? "?"}%). Corrected total is used downstream.`;
    }
    case "V3_MISSING_PO":
      return `V3: ${b.canonical_name ?? "this vendor"} requires a purchase order on every bill, but none was found on the document.`;
    case "V4_ROUND_NUMBER":
      return `V4: round-number total ${fmtMoney(b.total_cad)} (≥ $1,000). Low-weight flag only — routing follows the normal tier.`;
    default:
      return flag;
  }
}

export default function FindingsView({ data }: { data: IntakeData }) {
  const dups = data.bills.filter((b) =>
    b.flags.some((f) => f === "DUPLICATE" || f === "LIKELY_DUPLICATE")
  );
  const validations = data.bills.filter((b) =>
    b.flags.some((f) => f.startsWith("V"))
  );
  const vendorName = (id: string) =>
    data.register.find((v) => v.vendor_id === id)?.canonical_name ?? id;

  return (
    <div>
      <SectionTitle
        title="Findings"
        sub="Everything the deterministic checks caught: duplicates, split-dodge clusters, and validation flags — each with the bill refs and the rule that fired."
      />

      <h3 className="group-title">
        Duplicates ({dups.length})
      </h3>
      {dups.length === 0 && <p className="muted">No duplicates found.</p>}
      <div className="cards">
        {dups.map((b) => (
          <div className="card" key={b.bill_id}>
            <div className="card-head">
              <div>
                <div className="card-title">
                  {b.bill_id} — {b.canonical_name ?? b.vendor_text}
                </div>
                <div className="sub-id mono">
                  invoice {b.invoice_number ?? "—"} · {b.invoice_date} ·{" "}
                  {fmtMoney(b.total_cad)}
                </div>
              </div>
              <ActionChip action={b.action} />
            </div>
            <p className="finding-text">{dupExplanation(b)}</p>
            <div>{b.flags.map((f) => <FlagChip key={f} flag={f} />)}</div>
          </div>
        ))}
      </div>

      <h3 className="group-title">
        Split-dodge clusters ({data.splitClusters.length})
      </h3>
      {data.splitClusters.length === 0 && (
        <p className="muted">No split-dodge clusters found.</p>
      )}
      <div className="cards">
        {data.splitClusters.map((c) => {
          const members = data.bills.filter((b) =>
            c.bill_ids.includes(b.bill_id)
          );
          return (
            <div className="card" key={`${c.vendor_id}-${c.po}`}>
              <div className="card-head">
                <div>
                  <div className="card-title">
                    {vendorName(c.vendor_id)} · PO {c.po}
                  </div>
                  <div className="sub-id mono">
                    {c.cluster_size} invoices · {c.window_days}-day window ·
                    cluster sum {fmtMoney(c.cluster_sum)}
                  </div>
                </div>
                <ActionChip action="SEND_TO_DIRECTOR" />
              </div>
              <p className="finding-text">
                Each invoice sits in the $4,000–$5,000 band but the cluster
                sums to {fmtMoney(c.cluster_sum)} — above the $5,000 director
                tier. Routed to the director as a possible approval split.
              </p>
              <ul className="member-list">
                {members.map((m) => (
                  <li key={m.bill_id} className="mono">
                    {m.bill_id} — invoice {m.invoice_number} —{" "}
                    {m.invoice_date} — {fmtMoney(m.total_cad)}
                  </li>
                ))}
              </ul>
              <div>
                <FlagChip flag="SPLIT_DODGE" />
              </div>
            </div>
          );
        })}
      </div>

      <h3 className="group-title">
        Validation flags ({validations.length})
      </h3>
      {validations.length === 0 && (
        <p className="muted">No validation flags raised.</p>
      )}
      <div className="cards">
        {validations.map((b) => (
          <div className="card" key={b.bill_id}>
            <div className="card-head">
              <div>
                <div className="card-title">
                  {b.bill_id} — {b.canonical_name ?? b.vendor_text}
                </div>
                <div className="sub-id mono">
                  invoice {b.invoice_number ?? "—"} · {b.invoice_date} ·{" "}
                  {fmtMoney(b.total_cad)}
                </div>
              </div>
              <ActionChip action={b.action} />
            </div>
            {b.flags
              .filter((f) => f.startsWith("V"))
              .map((f) => (
                <p className="finding-text" key={f}>
                  {validationExplanation(b, f)}
                </p>
              ))}
            <div>{b.flags.map((f) => <FlagChip key={f} flag={f} />)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
