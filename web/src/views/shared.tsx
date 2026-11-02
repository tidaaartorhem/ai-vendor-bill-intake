export function fmtMoney(n: number, digits = 2): string {
  return (
    "$" +
    n.toLocaleString("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    })
  );
}

export function fmtDate(iso: string | null): string {
  return iso ?? "—";
}

const ACTION_CLASS: Record<string, string> = {
  AUTO_POST: "ok",
  SEND_TO_MANAGER: "warn",
  SEND_TO_DIRECTOR: "hot",
  HOLD_DUPLICATE: "bad",
  REQUEST_PO: "info",
  CORRECT_TOTAL: "fix",
};

export function ActionChip({ action }: { action: string }) {
  const cls = ACTION_CLASS[action] ?? "neutral";
  return <span className={`pill ${cls}`}>{action.replace(/_/g, " ")}</span>;
}

const FLAG_LABELS: Record<string, string> = {
  DUPLICATE: "Duplicate — D1 exact",
  LIKELY_DUPLICATE: "Likely duplicate — D2 near",
  V1_FUTURE_DATED: "Future-dated — V1",
  V2_UNFOOTED_TOTAL: "Unfooted total — V2",
  V3_MISSING_PO: "Missing PO — V3",
  V4_ROUND_NUMBER: "Round-number total — V4",
  SPLIT_DODGE: "Split-dodge cluster",
  UNRESOLVED_VENDOR: "Unresolved vendor",
};

export function FlagChip({ flag }: { flag: string }) {
  return (
    <span className="pill flag" title={flag}>
      {FLAG_LABELS[flag] ?? flag}
    </span>
  );
}

export function SectionTitle({
  title,
  sub,
}: {
  title: string;
  sub?: string;
}) {
  return (
    <div className="section-head">
      <h2>{title}</h2>
      {sub && <p className="muted">{sub}</p>}
    </div>
  );
}
