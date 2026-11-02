import { useState } from "react";
import type { IntakeData } from "../data";
import {
  REPLAY_DATE,
  checkFutureDated,
  checkMissingPO,
  checkRoundNumber,
  checkUnfooted,
  dedupeBill,
  extractBill,
  fxToCad,
  normalizeVendor,
  tierOf,
} from "../rules";
import { ActionChip, FlagChip, SectionTitle, fmtMoney } from "./shared";

const EXAMPLE_DUPLICATE = `Maple Packaging Ltd.
Invoice # 48291
Date: Oct 30 2026
PO: PO-1001
Currency: CAD

2 x White Hanging Heart T-Light Holder @ $2.95

Subtotal: $5.90
Tax (HST 13%): $0.77
Total: $6.67
`;

const EXAMPLE_CLEAN = `Bayview Stationery Co
Invoice # 60012
Date: Oct 29 2026
Currency: CAD

5 x Red Retrospot Mug @ $1.25

Subtotal: $6.25
Tax (HST 13%): $0.81
Total: $7.06
`;

interface PasteResult {
  extracted: ReturnType<typeof extractBill>;
  vendorId: string | null;
  canonical: string | null;
  jaccard: number | null;
  flags: string[];
  notes: string[];
  action: string;
  route: string;
  totalCad: number;
  headerTotalCad: number | null;
}

function runPaste(text: string, data: IntakeData): PasteResult | { error: string } {
  const extracted = extractBill(text);
  if (!extracted.vendor_name) return { error: "No vendor name found on the first line." };
  const norm = normalizeVendor(extracted.vendor_name, data.register) as {
    resolved: boolean;
    vendor_id: string | null;
    canonical_name?: string;
    jaccard?: number;
  };
  const vendor = data.register.find((v) => v.vendor_id === norm.vendor_id);
  const foreignTotal =
    extracted.currency === "CAD"
      ? (extracted.total ?? 0)
      : (extracted.total_foreign ?? 0);
  let totalCad = fxToCad(foreignTotal, extracted.currency, data.fx);
  let headerTotalCad: number | null = null;
  const flags: string[] = [];
  const notes: string[] = [];

  if (!norm.resolved || !vendor) {
    notes.push("Vendor name did not resolve to the register (Jaccard < 0.60) — needs a human look.");
    return {
      extracted,
      vendorId: null,
      canonical: null,
      jaccard: null,
      flags: ["UNRESOLVED_VENDOR"],
      notes,
      action: "SEND_TO_MANAGER",
      route: "REVIEW",
      totalCad,
      headerTotalCad,
    };
  }

  const dd = dedupeBill(
    {
      invoice_number: extracted.invoice_number,
      invoice_date: extracted.invoice_date ?? undefined,
      vendor_id: norm.vendor_id!,
      total_cad: totalCad,
    },
    data.posted
  ) as { is_duplicate: boolean; likely_duplicate: boolean; match_type: string | null };
  if (dd.is_duplicate) flags.push("DUPLICATE");
  else if (dd.likely_duplicate) flags.push("LIKELY_DUPLICATE");

  if (extracted.invoice_date) {
    const v1 = checkFutureDated(extracted.invoice_date, REPLAY_DATE);
    if (v1.future_dated) flags.push("V1_FUTURE_DATED");
  }

  const v2 = checkUnfooted({
    header_total: foreignTotal,
    line_items: extracted.line_items,
    subtotal: extracted.subtotal,
    tax: extracted.tax,
  });
  if (v2.unfooted) {
    flags.push("V2_UNFOOTED_TOTAL");
    totalCad = fxToCad(v2.corrected_total as number, extracted.currency, data.fx);
    headerTotalCad = fxToCad(foreignTotal, extracted.currency, data.fx);
    notes.push(
      `Header total does not foot: printed ${fmtMoney(foreignTotal)} vs true ${fmtMoney(v2.corrected_total as number)} — corrected total used.`
    );
  }

  const v3 = checkMissingPO(extracted.po, { po_required: vendor.po_required ?? false });
  if (v3.missing_po) flags.push("V3_MISSING_PO");

  const v4 = checkRoundNumber(totalCad);
  if (v4.round_number) {
    flags.push("V4_ROUND_NUMBER");
    notes.push("Round-number total ≥ $1,000 — informational flag only; routing follows the tier.");
  }

  notes.push("Split-dodge detection needs the full batch, so it is not run on a single pasted bill.");

  let action: string;
  let route: string;
  if (flags.includes("DUPLICATE") || flags.includes("LIKELY_DUPLICATE")) {
    action = "HOLD_DUPLICATE";
    route = "REVIEW";
  } else if (flags.includes("V2_UNFOOTED_TOTAL")) {
    action = "CORRECT_TOTAL";
    route = "REVIEW";
  } else if (flags.includes("V3_MISSING_PO")) {
    action = "REQUEST_PO";
    route = "REVIEW";
  } else if (flags.includes("V1_FUTURE_DATED")) {
    action = "SEND_TO_MANAGER";
    route = "MANAGER";
  } else {
    const t = tierOf(totalCad);
    action = t.action;
    route = t.route;
  }

  return {
    extracted,
    vendorId: norm.vendor_id,
    canonical: norm.canonical_name ?? null,
    jaccard: norm.jaccard ?? null,
    flags,
    notes,
    action,
    route,
    totalCad,
    headerTotalCad,
  };
}

export default function PasteView({ data }: { data: IntakeData }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<PasteResult | { error: string } | null>(null);

  const run = () => {
    if (!text.trim()) {
      setResult({ error: "Paste a bill first." });
      return;
    }
    setResult(runPaste(text, data));
  };

  const loadExample = (kind: "dup" | "clean") => {
    const t = kind === "dup" ? EXAMPLE_DUPLICATE : EXAMPLE_CLEAN;
    setText(t);
    setResult(runPaste(t, data));
  };

  const ok = result != null && !("error" in result) ? (result as PasteResult) : null;

  return (
    <div>
      <SectionTitle
        title="Paste a bill"
        sub="Runs the same deterministic rules in your browser: extract, resolve the vendor, dedupe against the posted register, validate, and route."
      />
      <div className="paste-grid">
        <div>
          <textarea
            className="paste-box"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"Paste the bill document text here…"}
            rows={18}
            spellCheck={false}
          />
          <div className="paste-actions">
            <button className="btn primary" onClick={run}>
              Run intake
            </button>
            <button className="btn" onClick={() => loadExample("dup")}>
              Try an example: duplicate resubmission
            </button>
            <button className="btn" onClick={() => loadExample("clean")}>
              Try an example: clean bill
            </button>
          </div>
        </div>
        <div>
          {result && "error" in result && <p className="note">{result.error}</p>}
          {ok && (
            <div className="result-panel">
              <div className="result-head">
                <ActionChip action={ok.action} />
                <span className="muted">route: {ok.route}</span>
              </div>
              <dl className="kv">
                <div><dt>Vendor (as written)</dt><dd className="mono">{ok.extracted.vendor_name}</dd></div>
                <div><dt>Resolved vendor</dt><dd className="mono">{ok.canonical ?? "unresolved"}{ok.jaccard != null ? ` (Jaccard ${ok.jaccard.toFixed(2)})` : ""}</dd></div>
                <div><dt>Invoice #</dt><dd className="mono">{ok.extracted.invoice_number ?? "—"}</dd></div>
                <div><dt>Invoice date</dt><dd className="mono">{ok.extracted.invoice_date ?? "—"}</dd></div>
                <div><dt>PO</dt><dd className="mono">{ok.extracted.po ?? "—"}</dd></div>
                <div><dt>Currency</dt><dd className="mono">{ok.extracted.currency}</dd></div>
                <div><dt>Lines</dt><dd className="mono">{ok.extracted.line_items.length} (subtotal {fmtMoney(ok.extracted.subtotal)}, tax {fmtMoney(ok.extracted.tax)})</dd></div>
                <div><dt>Total (CAD)</dt><dd className="mono">{fmtMoney(ok.totalCad)}{ok.headerTotalCad != null ? ` — header showed ${fmtMoney(ok.headerTotalCad)}` : ""}</dd></div>
              </dl>
              <div className="flag-row">
                {ok.flags.length === 0 ? <span className="muted">No flags — clean bill.</span> :
                  ok.flags.map((f) => <FlagChip key={f} flag={f} />)}
              </div>
              {ok.notes.length > 0 && (
                <ul className="notes">
                  {ok.notes.map((n, i) => <li key={i}>{n}</li>)}
                </ul>
              )}
            </div>
          )}
          {!result && (
            <p className="muted">
              Nothing run yet. The duplicate example reuses invoice #48291 from
              Maple Packaging Ltd., which is already in the posted register —
              expect a D1 hold. The clean example is a small stationery bill —
              expect auto-intake.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
