/**
 * data.ts — runtime JSON loading. Everything is fetched from ./data/ at
 * runtime; pipeline-results.json and eval.json may not exist yet (the
 * Python engine writes them in parallel), so the app degrades gracefully
 * with a "results pending" note instead of failing.
 */
import { runIntake } from "./rules";
import type { FxTable, PipelineBill, PostedBill, SplitCluster, VendorRef } from "./rules";

export interface GoldenBill {
  bill_id: string;
  vendor_id: string;
  invoice_number: string | null;
  invoice_date: string;
  total_cad: number;
  expected_action: string;
}

export interface IntakeData {
  bills: PipelineBill[];
  splitClusters: SplitCluster[];
  register: VendorRef[];
  posted: PostedBill[];
  fx: FxTable;
  corpusStats: Record<string, unknown>;
  goldenSet: GoldenBill[];
  rawBills: Array<{ bill_id: string; bill_text: string; seed_flags: string[] }>;
  eval: Record<string, unknown> | null;
  /** True when the Python pipeline's own results were available at runtime. */
  fromPipelineResults: boolean;
  pipelineNote: string | null;
}

const BASE = import.meta.env.BASE_URL || "/";

async function fetchJson<T>(name: string): Promise<T | null> {
  try {
    const res = await fetch(`${BASE}data/${name}`);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

interface PipelineRow {
  bill_id: string;
  action?: string;
  route?: string;
  total_cad?: number;
  vendor_id?: string;
  vendor_name?: string;
  canonical_name?: string;
  invoice_number?: string | null;
  invoice_date?: string | null;
  currency?: string;
  po?: string | null;
  flags?: string[];
}

/** Tolerant reader: accepts a bare array, {bills:[...]} or {results:[...]}. */
function readPipelineRows(raw: unknown): PipelineRow[] | null {
  const arr = Array.isArray(raw)
    ? raw
    : raw != null && typeof raw === "object"
      ? ((raw as any).bills ?? (raw as any).results ?? null)
      : null;
  if (!Array.isArray(arr) || arr.length === 0) return null;
  if (typeof arr[0]?.bill_id !== "string" || typeof arr[0]?.action !== "string")
    return null;
  return arr as PipelineRow[];
}

export async function loadIntakeData(): Promise<IntakeData> {
  const [billsRaw, register, posted, fx, corpusStats, goldenSet, pipelineRaw, evalRaw] =
    await Promise.all([
      fetchJson<Array<{ bill_id: string; bill_text: string; seed_flags: string[] }>>("bills.json"),
      fetchJson<VendorRef[]>("vendor-register.json"),
      fetchJson<PostedBill[]>("posted-register.json"),
      fetchJson<FxTable>("fx-table.json"),
      fetchJson<Record<string, unknown>>("corpus-stats.json"),
      fetchJson<GoldenBill[]>("golden-set.json"),
      fetchJson<unknown>("pipeline-results.json"),
      fetchJson<Record<string, unknown>>("eval.json"),
    ]);
  if (!billsRaw || !register || !posted || !fx) {
    throw new Error("core data files (bills/vendor/posted/fx) failed to load");
  }

  // Always run the in-browser mirror: it powers Paste-a-bill and the
  // Findings tab, and backs the Queue when pipeline results are pending.
  const { bills, splitClusters } = runIntake(
    billsRaw.map((b) => ({ bill_id: b.bill_id, bill_text: b.bill_text })),
    register,
    posted,
    fx
  );

  let fromPipelineResults = false;
  let pipelineNote: string | null = null;
  const rows = pipelineRaw != null ? readPipelineRows(pipelineRaw) : null;
  if (rows) {
    // Prefer the Python engine's rows for the Queue; join display fields
    // from the mirror run by bill_id.
    const byId = new Map(bills.map((b) => [b.bill_id, b]));
    const merged: PipelineBill[] = [];
    for (const r of rows) {
      const m = byId.get(r.bill_id);
      if (!m) continue;
      merged.push({
        ...m,
        action: r.action ?? m.action,
        route: r.route ?? m.route,
        total_cad: typeof r.total_cad === "number" ? r.total_cad : m.total_cad,
        flags: Array.isArray(r.flags) && r.flags.length > 0 ? r.flags : m.flags,
      });
    }
    if (merged.length > 0) {
      fromPipelineResults = true;
    } else {
      pipelineNote = "pipeline-results.json was present but unreadable — showing the in-browser mirror instead.";
    }
    if (fromPipelineResults) {
      return {
        bills: merged,
        splitClusters,
        register,
        posted,
        fx,
        corpusStats: corpusStats ?? {},
        goldenSet: goldenSet ?? [],
        rawBills: billsRaw,
        eval: evalRaw,
        fromPipelineResults,
        pipelineNote,
      };
    }
  } else if (pipelineRaw != null) {
    pipelineNote = "pipeline-results.json was present but unreadable — showing the in-browser mirror instead.";
  }

  return {
    bills,
    splitClusters,
    register,
    posted,
    fx,
    corpusStats: corpusStats ?? {},
    goldenSet: goldenSet ?? [],
    rawBills: billsRaw,
    eval: evalRaw,
    fromPipelineResults,
    pipelineNote,
  };
}
