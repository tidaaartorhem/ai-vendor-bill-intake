import { useMemo } from "react";
import type { IntakeData } from "../data";
import { SectionTitle, fmtMoney } from "./shared";

export default function VendorsView({ data }: { data: IntakeData }) {
  const rows = useMemo(() => {
    return data.register
      .map((v) => {
        const bills = data.bills.filter((b) => b.vendor_id === v.vendor_id);
        const variants = Array.from(
          new Set(
            bills
              .map((b) => b.vendor_text)
              .filter((t) => t && t !== v.canonical_name)
          )
        );
        const total = bills.reduce((s, b) => s + b.total_cad, 0);
        return { v, count: bills.length, variants, total };
      })
      .sort((a, b) => b.count - a.count || b.total - a.total);
  }, [data]);

  const withBills = rows.filter((r) => r.count > 0);

  return (
    <div>
      <SectionTitle
        title="Vendor Register"
        sub="40 canonical vendors. Alias variants are resolved by token-set Jaccard ≥ 0.60 and folded into the canonical record."
      />
      <div className="chips">
        <span className="chip">
          <strong>{data.register.length}</strong> vendors
        </span>
        <span className="chip">
          <strong>{data.register.filter((v) => v.currency === "CAD").length}</strong> CAD ·{" "}
          <strong>{data.register.filter((v) => v.currency !== "CAD").length}</strong> foreign
        </span>
        <span className="chip">
          <strong>{data.register.filter((v) => v.po_required).length}</strong> PO-required
        </span>
        <span className="chip">
          <strong>{withBills.length}</strong> with bills this batch
        </span>
      </div>

      <div className="cards">
        {rows.map(({ v, count, variants, total }) => (
          <div className="card" key={v.vendor_id}>
            <div className="card-head">
              <div>
                <div className="card-title">{v.canonical_name}</div>
                <div className="sub-id mono">
                  {v.vendor_id} · {v.currency}
                  {v.po_required ? " · PO required" : ""}
                </div>
              </div>
              <div className="card-stat">
                <strong>{count}</strong>
                <span>bills</span>
              </div>
            </div>
            <div className="card-meta">
              <span>Batch total {fmtMoney(total)}</span>
            </div>
            {variants.length > 0 ? (
              <div className="variants">
                <span className="muted">Seen as: </span>
                {variants.map((t) => (
                  <code key={t}>{t}</code>
                ))}
              </div>
            ) : (
              <div className="variants muted">No alias variants observed.</div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
