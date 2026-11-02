import { useMemo, useState } from "react";
import type { IntakeData } from "../data";
import { ActionChip, FlagChip, SectionTitle, fmtDate, fmtMoney } from "./shared";

const ACTION_ORDER = [
  "HOLD_DUPLICATE",
  "REQUEST_PO",
  "CORRECT_TOTAL",
  "SEND_TO_DIRECTOR",
  "SEND_TO_MANAGER",
  "AUTO_POST",
];

export default function QueueView({ data }: { data: IntakeData }) {
  const [approved, setApproved] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>("ALL");

  const approvedSet = useMemo(() => new Set(approved), [approved]);
  const queue = data.bills.filter((b) => !approvedSet.has(b.bill_id));
  const postedNow = data.bills.filter((b) => approvedSet.has(b.bill_id));

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const b of queue) c[b.action] = (c[b.action] ?? 0) + 1;
    return c;
  }, [queue]);

  const visible = useMemo(() => {
    const rows = filter === "ALL" ? queue : queue.filter((b) => b.action === filter);
    return [...rows].sort(
      (a, b) =>
        ACTION_ORDER.indexOf(a.action) - ACTION_ORDER.indexOf(b.action)
    );
  }, [queue, filter]);

  const approve = (billId: string) => setApproved((s) => [...s, billId]);

  return (
    <div>
      <SectionTitle
        title="Intake Queue"
        sub="Every bill the desk captured, extracted, normalized, deduped and routed. Nothing posts to the ledger until you approve."
      />
      <div className="chips">
        <span className="chip">
          <strong>{queue.length}</strong> in queue
        </span>
        {ACTION_ORDER.filter((a) => counts[a]).map((a) => (
          <span className="chip" key={a}>
            <strong>{counts[a]}</strong> {a.replace(/_/g, " ").toLowerCase()}
          </span>
        ))}
        <span className="chip muted-chip">
          source:{" "}
          {data.fromPipelineResults
            ? "pipeline-results.json"
            : "in-browser rules mirror"}
        </span>
      </div>
      {data.pipelineNote && <p className="note">{data.pipelineNote}</p>}

      <div className="filter-row">
        <label>
          Filter{" "}
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="ALL">All actions</option>
            {ACTION_ORDER.filter((a) => counts[a]).map((a) => (
              <option value={a} key={a}>
                {a.replace(/_/g, " ")}
              </option>
            ))}
          </select>
        </label>
      </div>

      <table className="board">
        <thead>
          <tr>
            <th>Vendor</th>
            <th>Invoice #</th>
            <th>Date</th>
            <th className="num">Total (CAD)</th>
            <th>Flags</th>
            <th>Action</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((b) => (
            <tr key={b.bill_id}>
              <td>
                <div className="vendor">{b.canonical_name ?? b.vendor_text}</div>
                <div className="sub-id">{b.bill_id}</div>
              </td>
              <td className="mono">{b.invoice_number ?? "—"}</td>
              <td className="mono">{fmtDate(b.invoice_date)}</td>
              <td className="num mono">
                {fmtMoney(b.total_cad)}
                {b.header_total_cad != null && (
                  <div className="sub-id">
                    header showed {fmtMoney(b.header_total_cad)}
                  </div>
                )}
              </td>
              <td>
                {b.flags.length === 0 ? (
                  <span className="muted">—</span>
                ) : (
                  b.flags.map((f) => <FlagChip key={f} flag={f} />)
                )}
              </td>
              <td>
                <ActionChip action={b.action} />
              </td>
              <td>
                <button className="btn" onClick={() => approve(b.bill_id)}>
                  Approve
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {visible.length === 0 && (
        <p className="muted">Queue is clear for this filter.</p>
      )}

      {postedNow.length > 0 && (
        <div className="posted-panel">
          <h3>Posted this session ({postedNow.length})</h3>
          <p className="muted">
            Approved client-side in this browser session. Nothing was written
            to any ledger.
          </p>
          <ul>
            {postedNow.map((b) => (
              <li key={b.bill_id} className="mono">
                {b.bill_id} — {b.canonical_name ?? b.vendor_text} —{" "}
                {b.invoice_number ?? "no number"} — {fmtMoney(b.total_cad)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
