/**
 * rules.ts — TypeScript mirror of the deterministic InTray intake rules.
 *
 * Mirrors the Python engine rule-for-rule: extract (ordered invoice-number
 * regexes, multi-format dates, PO refs, "qty x DESC @ $price" lines,
 * subtotal/tax/total), token-set Jaccard >= 0.60 alias resolution
 * (tie-break: longest canonical name), ISO dates, FX conversion to CAD,
 * D1 exact / D2 near-duplicate dedupe, V1–V4 validation flags, split-dodge
 * detection, and tier routing. Totals to 2 decimals, dates ISO.
 */

export const REPLAY_DATE = "2026-11-02";

export const JACCARD_THRESHOLD = 0.6;
export const D2_TOTAL_PCT = 1.0; // near-dupe: total within 1%
export const D2_DATE_DAYS = 7; // near-dupe: date within 7 days
export const V2_ABS_TOL = 0.05; // unfooted: diff > $0.05
export const V2_PCT_TOL = 0.5; // unfooted: diff > 0.5%
export const V4_MIN_TOTAL = 1000; // round-number flag floor
export const SPLIT_BAND_LO = 4000; // split-dodge invoice band
export const SPLIT_BAND_HI = 5000;
export const SPLIT_WINDOW_DAYS = 7;
export const SPLIT_SUM_FLOOR = 5000;
export const TIER_AUTO_MAX = 1000; // < $1k AUTO-INTAKE
export const TIER_MANAGER_MAX = 5000; // <= $5k MANAGER, else DIRECTOR

export function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

/* ------------------------------------------------------------------ types */

export interface VendorRef {
  vendor_id: string;
  canonical_name: string;
  po_required?: boolean;
  currency?: string;
}

export interface PostedBill {
  vendor_id: string;
  invoice_number: string;
  invoice_date: string;
  total_cad: number;
}

export interface FxTable {
  USD: number;
  EUR: number;
  GBP: number;
  base: string;
}

export interface LineItem {
  qty: number;
  description: string;
  unit_price: number;
  line_total: number;
}

export interface ExtractResult {
  vendor_name: string;
  invoice_number: string | null;
  invoice_date: string | null;
  po: string | null;
  currency: string;
  line_items: LineItem[];
  subtotal: number;
  tax: number;
  total?: number;
  total_foreign?: number;
  currency_symbol?: string;
}

/* ------------------------------------------------------------------ dates */

const MONTHS: Record<string, number> = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
};

const pad = (s: string | number) => String(s).padStart(2, "0");

/** Parse "Oct 28 2026" / "28/10/2026" / "2026-10-28" -> "2026-10-28". */
export function parseDateToISO(raw: string): string | null {
  const s = raw.trim();
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (m) return `${m[1]}-${m[2]}-${m[3]}`;
  m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/);
  if (m) return `${m[3]}-${pad(m[2])}-${pad(m[1])}`;
  m = s.match(/^([A-Za-z]+)\s+(\d{1,2}),?\s*(\d{4})$/);
  if (m) {
    const mo = MONTHS[m[1].slice(0, 3).toLowerCase()];
    if (mo) return `${m[3]}-${pad(mo)}-${pad(m[2])}`;
  }
  return null;
}

function utcDay(iso: string): number {
  const [y, mo, d] = iso.split("-").map(Number);
  return Date.UTC(y, mo - 1, d);
}

export function daysBetween(aISO: string, bISO: string): number {
  return Math.abs(Math.round((utcDay(aISO) - utcDay(bISO)) / 86400000));
}

/* ---------------------------------------------------------------- extract */

const MONEY = String.raw`(?:US\$|€|£|\$)`;
const NUM = String.raw`([\d,]+\.\d{2})`;

function parseMoney(s: string): number {
  return parseFloat(s.replace(/,/g, ""));
}

function detectCurrencySymbol(text: string): string {
  if (text.includes("US$")) return "US$";
  if (text.includes("€")) return "€";
  if (text.includes("£")) return "£";
  return "$";
}

/**
 * Extract structured fields from a bill's document text. Invoice-number
 * patterns are tried in order: "Invoice #", "INV-", then "No.".
 */
export function extractBill(billText: string): ExtractResult {
  const lines = billText.split("\n");
  const vendor_name = (lines.find((l) => l.trim().length > 0) ?? "").trim();

  let invoice_number: string | null = null;
  const invPatterns = [
    /Invoice\s*#\s*(\S+)/i,
    /\b(INV-\S+)/,
    /No\.\s*(\S+)/,
  ];
  for (const re of invPatterns) {
    const m = billText.match(re);
    if (m) {
      invoice_number = m[1];
      break;
    }
  }

  let invoice_date: string | null = null;
  const dateLine = lines.find((l) => /^Date:/i.test(l.trim()));
  if (dateLine) invoice_date = parseDateToISO(dateLine.replace(/^Date:/i, ""));

  let po: string | null = null;
  const pm = billText.match(/(?:P\.?\s*O\.?|PO)\s*:?\s*(PO-\d+)/i);
  if (pm) po = pm[1];

  const cm = billText.match(/^Currency:\s*([A-Z]{3})\s*$/m);
  const currency = cm ? cm[1] : "CAD";

  const line_items: LineItem[] = [];
  const lineRe = new RegExp(
    String.raw`^(\d+)\s*x\s+(.+?)\s*@\s*${MONEY}${NUM}\s*$`
  );
  for (const line of lines) {
    const m = line.match(lineRe);
    if (m) {
      const qty = parseInt(m[1], 10);
      const unit_price = parseMoney(m[3]);
      line_items.push({
        qty,
        description: m[2].trim(),
        unit_price,
        line_total: round2(qty * unit_price),
      });
    }
  }

  const grab = (re: RegExp): number => {
    const m = billText.match(re);
    return m ? parseMoney(m[1]) : 0;
  };
  const subtotal = grab(new RegExp(String.raw`^Subtotal:\s*${MONEY}${NUM}\s*$`, "m"));
  const tax = grab(new RegExp(String.raw`^Tax\s*\([^)]*\):\s*${MONEY}${NUM}\s*$`, "m"));
  const totalValue = grab(new RegExp(String.raw`^Total:\s*${MONEY}${NUM}\s*$`, "m"));

  const base = {
    vendor_name,
    invoice_number,
    invoice_date,
    po,
    currency,
    line_items,
    subtotal,
    tax,
  };
  if (currency === "CAD") {
    return { ...base, total: totalValue };
  }
  return {
    ...base,
    total_foreign: totalValue,
    currency_symbol: detectCurrencySymbol(billText),
  };
}

/* ------------------------------------------------------------ normalization */

export function tokenize(s: string): string[] {
  return (s.toLowerCase().match(/[a-z0-9]+/g) ?? []);
}

export function jaccard(a: Set<string>, b: Set<string>): number {
  let inter = 0;
  for (const t of a) if (b.has(t)) inter++;
  const union = a.size + b.size - inter;
  return union === 0 ? 0 : inter / union;
}

/**
 * Resolve a display vendor name against the register with token-set
 * Jaccard >= 0.60; ties break toward the longest canonical name.
 */
export function normalizeVendor(
  vendorText: string,
  register: VendorRef[]
): Record<string, unknown> {
  const vt = new Set(tokenize(vendorText));
  let best: { vendor_id: string; canonical_name: string; score: number } | null =
    null;
  for (const v of register) {
    const score = jaccard(vt, new Set(tokenize(v.canonical_name)));
    if (
      !best ||
      score > best.score ||
      (score === best.score &&
        v.canonical_name.length > best.canonical_name.length)
    ) {
      best = { vendor_id: v.vendor_id, canonical_name: v.canonical_name, score };
    }
  }
  if (!best) return { resolved: false, vendor_id: null };
  if (best.score >= JACCARD_THRESHOLD) {
    return {
      resolved: true,
      vendor_id: best.vendor_id,
      canonical_name: best.canonical_name,
      jaccard: best.score,
    };
  }
  return {
    resolved: false,
    vendor_id: null,
    best_candidate: best.vendor_id,
    best_score: best.score,
  };
}

/* ------------------------------------------------------------------ dedupe */

export interface DedupeInput {
  invoice_number: string | null;
  invoice_date?: string;
  vendor_id: string;
  total_cad?: number;
}

/** D1 exact (vendor + invoice#) then D2 near-dupe (1% total, 7-day window). */
export function dedupeBill(
  bill: DedupeInput,
  posted: PostedBill[]
): Record<string, unknown> {
  const noMatch = {
    is_duplicate: false,
    likely_duplicate: false,
    match_type: null,
    action: null,
  };
  if (bill.invoice_number) {
    const m = posted.find(
      (p) =>
        p.vendor_id === bill.vendor_id &&
        p.invoice_number === bill.invoice_number
    );
    if (m) {
      return {
        is_duplicate: true,
        match_type: "D1_EXACT",
        matched_posted: {
          invoice_number: m.invoice_number,
          vendor_id: m.vendor_id,
        },
        action: "HOLD_DUPLICATE",
      };
    }
  }
  if (bill.invoice_date == null || bill.total_cad == null) return noMatch;
  const invoice_date = bill.invoice_date;
  const total_cad = bill.total_cad;
  for (const p of posted) {
    if (p.vendor_id !== bill.vendor_id) continue;
    if (p.invoice_number === bill.invoice_number) continue;
    if (p.total_cad === 0) continue;
    const total_diff_pct = round2(
      (Math.abs(total_cad - p.total_cad) / p.total_cad) * 100
    );
    const date_diff_days = daysBetween(invoice_date, p.invoice_date);
    if (total_diff_pct <= D2_TOTAL_PCT && date_diff_days <= D2_DATE_DAYS) {
      return {
        is_duplicate: false,
        likely_duplicate: true,
        match_type: "D2_NEAR",
        total_diff_pct,
        date_diff_days,
        action: "HOLD_DUPLICATE",
      };
    }
  }
  return noMatch;
}

/* --------------------------------------------------------------- validation */

export function checkFutureDated(
  invoiceDate: string,
  replayDate: string
): Record<string, unknown> {
  const future_dated = invoiceDate > replayDate;
  const days_after_replay = Math.round(
    (utcDay(invoiceDate) - utcDay(replayDate)) / 86400000
  );
  if (future_dated) {
    return {
      future_dated: true,
      days_after_replay,
      flag: "V1_FUTURE_DATED",
      action: "SEND_TO_MANAGER",
    };
  }
  return {
    future_dated: false,
    days_after_replay,
    flag: null,
    action: null,
  };
}

export interface UnfootedInput {
  header_total: number;
  line_items: Array<{ qty: number; unit_price: number }>;
  subtotal?: number;
  tax?: number;
}

/**
 * V2 unfooted: printed header total vs the true total (subtotal + tax when
 * present, else sum of line items). Fires when the difference exceeds $0.05
 * AND 0.5% of the true total.
 */
export function checkUnfooted(input: UnfootedInput): Record<string, unknown> {
  const sum_lines = round2(
    input.line_items.reduce((s, l) => s + l.qty * l.unit_price, 0)
  );
  const base =
    input.subtotal != null && input.tax != null
      ? round2(input.subtotal + input.tax)
      : sum_lines;
  const diff = round2(Math.abs(input.header_total - base));
  const diff_pct = base === 0 ? 0 : round2((diff / base) * 100);
  const unfooted = diff > V2_ABS_TOL && diff_pct > V2_PCT_TOL;
  return {
    unfooted,
    sum_lines,
    header_total: input.header_total,
    diff,
    diff_pct,
    corrected_total: base,
    flag: unfooted ? "V2_UNFOOTED_TOTAL" : null,
    action: unfooted ? "CORRECT_TOTAL" : null,
  };
}

export function checkMissingPO(
  po: string | null,
  vendor: { po_required: boolean }
): Record<string, unknown> {
  const missing_po = po == null && vendor.po_required;
  return {
    missing_po,
    flag: missing_po ? "V3_MISSING_PO" : null,
    action: missing_po ? "REQUEST_PO" : null,
  };
}

export function checkRoundNumber(totalCad: number): Record<string, unknown> {
  const t = tierOf(totalCad);
  const round_number = totalCad >= V4_MIN_TOTAL && Number.isInteger(totalCad);
  return {
    round_number,
    flag: round_number ? "V4_ROUND_NUMBER" : null,
    route: t.route,
    weight: round_number ? "low" : null,
    action: t.action,
  };
}

/* ------------------------------------------------------------ split-dodge */

export interface SplitInvoice {
  bill_id: string;
  invoice_date: string;
  po: string | null;
  total_cad: number;
  vendor_id: string;
}

/**
 * Split-dodge: same vendor + same PO, all inside a 7-day window, at least
 * one invoice in the $4k–$5k band, cluster sum above $5k.
 */
export function detectSplitDodge(
  invoices: SplitInvoice[]
): Record<string, unknown> {
  const cluster_size = invoices.length;
  const cluster_sum = round2(invoices.reduce((s, i) => s + i.total_cad, 0));
  const dates = invoices.map((i) => i.invoice_date).sort();
  const window_days =
    dates.length > 0
      ? Math.round((utcDay(dates[dates.length - 1]) - utcDay(dates[0])) / 86400000)
      : 0;
  const sameVendor = new Set(invoices.map((i) => i.vendor_id)).size === 1;
  const samePO =
    new Set(invoices.map((i) => i.po)).size === 1 && invoices[0]?.po != null;
  const inBand = invoices.some(
    (i) => i.total_cad >= SPLIT_BAND_LO && i.total_cad <= SPLIT_BAND_HI
  );
  const split_dodge =
    cluster_size >= 2 &&
    sameVendor &&
    samePO &&
    window_days <= SPLIT_WINDOW_DAYS &&
    inBand &&
    cluster_sum > SPLIT_SUM_FLOOR;
  return {
    split_dodge,
    cluster_size,
    cluster_sum,
    window_days,
    flag: split_dodge ? "SPLIT_DODGE" : null,
    action: split_dodge ? "SEND_TO_DIRECTOR" : null,
  };
}

/* ----------------------------------------------------------------- routing */

export interface Tier {
  route: "AUTO-INTAKE" | "MANAGER" | "DIRECTOR";
  action: "AUTO_POST" | "SEND_TO_MANAGER" | "SEND_TO_DIRECTOR";
}

export function tierOf(totalCad: number): Tier {
  if (totalCad < TIER_AUTO_MAX)
    return { route: "AUTO-INTAKE", action: "AUTO_POST" };
  if (totalCad <= TIER_MANAGER_MAX)
    return { route: "MANAGER", action: "SEND_TO_MANAGER" };
  return { route: "DIRECTOR", action: "SEND_TO_DIRECTOR" };
}

export function fxToCad(amount: number, currency: string, fx: FxTable): number {
  if (currency === "CAD") return round2(amount);
  const rate = (fx as unknown as Record<string, number>)[currency];
  if (rate == null) throw new Error(`no FX rate for ${currency}`);
  return round2(amount * rate);
}

export interface RouteBill {
  bill_id: string;
  currency: string;
  total: number;
  flags: string[];
}

/** Tier routing with USD/EUR/GBP -> CAD FX; any duplicate flag -> REVIEW. */
export function routeBills(input: {
  bills: RouteBill[];
  fx_table: FxTable;
  replay_date: string;
}): { results: Array<Record<string, unknown>> } {
  const results = input.bills.map((b) => {
    const total_cad = fxToCad(b.total, b.currency, input.fx_table);
    const dup = b.flags.some(
      (f) =>
        f === "DUPLICATE" ||
        f === "LIKELY_DUPLICATE" ||
        f.startsWith("D1") ||
        f.startsWith("D2")
    );
    if (dup) {
      return { bill_id: b.bill_id, action: "HOLD_DUPLICATE", route: "REVIEW", total_cad };
    }
    const t = tierOf(total_cad);
    return { bill_id: b.bill_id, action: t.action, route: t.route, total_cad };
  });
  return { results };
}

/* ----------------------------------------------------------- full pipeline */

export interface PipelineBill {
  bill_id: string;
  vendor_text: string;
  vendor_id: string | null;
  canonical_name: string | null;
  jaccard: number | null;
  invoice_number: string | null;
  invoice_date: string | null;
  currency: string;
  total_foreign: number;
  total_cad: number;
  header_total_cad: number | null;
  po: string | null;
  flags: string[];
  action: string;
  route: string;
  line_count: number;
  detail: Record<string, Record<string, unknown>>;
}

export interface SplitCluster {
  vendor_id: string;
  po: string;
  bill_ids: string[];
  cluster_size: number;
  cluster_sum: number;
  window_days: number;
}

/**
 * Run the full intake pipeline over a batch of bills. Precedence:
 * duplicate > split-dodge > unfooted > missing PO > future-dated > tier
 * (V4 round-number is informational only and never changes routing).
 */
export function runIntake(
  bills: Array<{ bill_id: string; bill_text: string }>,
  register: VendorRef[],
  posted: PostedBill[],
  fx: FxTable,
  replayDate: string = REPLAY_DATE
): { bills: PipelineBill[]; splitClusters: SplitCluster[] } {
  // First pass: extract + normalize + FX + per-bill checks.
  const work = bills.map((b) => {
    const ex = extractBill(b.bill_text);
    const norm = normalizeVendor(ex.vendor_name, register) as {
      resolved: boolean;
      vendor_id: string | null;
      canonical_name?: string;
      jaccard?: number;
    };
    const vendor = register.find((v) => v.vendor_id === norm.vendor_id);
    const foreignTotal =
      ex.currency === "CAD" ? (ex.total ?? 0) : (ex.total_foreign ?? 0);
    const total_cad = fxToCad(foreignTotal, ex.currency, fx);
    return { bill: b, ex, norm, vendor, total_cad, foreignTotal };
  });

  // Split detection needs the whole batch: group by (vendor_id, po).
  const groups = new Map<string, number[]>();
  work.forEach((w, i) => {
    if (w.norm.vendor_id && w.ex.po && w.ex.invoice_date) {
      const key = `${w.norm.vendor_id}|${w.ex.po}`;
      const arr = groups.get(key) ?? [];
      arr.push(i);
      groups.set(key, arr);
    }
  });
  const splitIdx = new Set<number>();
  const splitClusters: SplitCluster[] = [];
  for (const idxs of groups.values()) {
    const r = detectSplitDodge(
      idxs.map((i) => ({
        bill_id: work[i].bill.bill_id,
        invoice_date: work[i].ex.invoice_date!,
        po: work[i].ex.po,
        total_cad: work[i].total_cad,
        vendor_id: work[i].norm.vendor_id!,
      }))
    ) as { split_dodge: boolean; cluster_size: number; cluster_sum: number; window_days: number };
    if (r.split_dodge) {
      idxs.forEach((i) => splitIdx.add(i));
      const first = work[idxs[0]];
      splitClusters.push({
        vendor_id: first.norm.vendor_id!,
        po: first.ex.po!,
        bill_ids: idxs.map((i) => work[i].bill.bill_id),
        cluster_size: r.cluster_size,
        cluster_sum: r.cluster_sum,
        window_days: r.window_days,
      });
    }
  }

  const out: PipelineBill[] = work.map((w, i) => {
    const flags: string[] = [];
    const detail: Record<string, Record<string, unknown>> = {};
    let action: string;
    let route: string;
    let total_cad = w.total_cad;
    let header_total_cad: number | null = null;

    if (!w.norm.resolved) {
      flags.push("UNRESOLVED_VENDOR");
      const t = tierOf(total_cad);
      action = "SEND_TO_MANAGER";
      route = t.route === "AUTO-INTAKE" ? "REVIEW" : t.route;
    } else {
      // Dedupe.
      const dd = dedupeBill(
        {
          invoice_number: w.ex.invoice_number,
          invoice_date: w.ex.invoice_date ?? undefined,
          vendor_id: w.norm.vendor_id!,
          total_cad,
        },
        posted
      ) as { is_duplicate: boolean; likely_duplicate: boolean; match_type: string | null; action: string | null; matched_posted?: unknown; total_diff_pct?: number; date_diff_days?: number };
      detail.dedupe = dd as Record<string, unknown>;
      if (dd.is_duplicate) flags.push("DUPLICATE");
      else if (dd.likely_duplicate) flags.push("LIKELY_DUPLICATE");

      // V1 future-dated.
      if (w.ex.invoice_date) {
        const v1 = checkFutureDated(w.ex.invoice_date, replayDate);
        detail.v1 = v1;
        if (v1.future_dated) flags.push("V1_FUTURE_DATED");
      }

      // V2 unfooted.
      const headerForeign =
        w.ex.currency === "CAD" ? (w.ex.total ?? 0) : (w.ex.total_foreign ?? 0);
      const v2 = checkUnfooted({
        header_total: headerForeign,
        line_items: w.ex.line_items,
        subtotal: w.ex.subtotal,
        tax: w.ex.tax,
      });
      detail.v2 = v2;
      if (v2.unfooted) {
        flags.push("V2_UNFOOTED_TOTAL");
        const correctedForeign = v2.corrected_total as number;
        total_cad = fxToCad(correctedForeign, w.ex.currency, fx);
        header_total_cad = fxToCad(headerForeign, w.ex.currency, fx);
      }

      // V3 missing PO.
      const v3 = checkMissingPO(w.ex.po, {
        po_required: w.vendor?.po_required ?? false,
      });
      detail.v3 = v3;
      if (v3.missing_po) flags.push("V3_MISSING_PO");

      // V4 round-number (informational).
      const v4 = checkRoundNumber(total_cad);
      detail.v4 = v4;
      if (v4.round_number) flags.push("V4_ROUND_NUMBER");

      // Split-dodge (batch).
      if (splitIdx.has(i)) flags.push("SPLIT_DODGE");

      // Precedence: duplicate > split > unfooted > missing PO > future > tier.
      if (flags.includes("DUPLICATE") || flags.includes("LIKELY_DUPLICATE")) {
        action = "HOLD_DUPLICATE";
        route = "REVIEW";
      } else if (flags.includes("SPLIT_DODGE")) {
        action = "SEND_TO_DIRECTOR";
        route = "DIRECTOR";
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
        const t = tierOf(total_cad);
        action = t.action;
        route = t.route;
      }
    }

    return {
      bill_id: w.bill.bill_id,
      vendor_text: w.ex.vendor_name,
      vendor_id: w.norm.vendor_id,
      canonical_name: (w.norm.canonical_name as string | undefined) ?? null,
      jaccard: (w.norm.jaccard as number | undefined) ?? null,
      invoice_number: w.ex.invoice_number,
      invoice_date: w.ex.invoice_date,
      currency: w.ex.currency,
      total_foreign: w.foreignTotal,
      total_cad,
      header_total_cad,
      po: w.ex.po,
      flags,
      action,
      route,
      line_count: w.ex.line_items.length,
      detail,
    };
  });

  return { bills: out, splitClusters };
}
