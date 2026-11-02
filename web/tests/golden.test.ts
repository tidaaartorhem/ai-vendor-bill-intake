/**
 * Golden-set check (NON-GATING): run the TS mirror over all 120 bills and
 * compare the recommended action against the 30 hand-labeled golden bills.
 * Reports the agreement rate honestly — it is logged, not forced to 100%.
 */
import { describe, expect, it } from "vitest";
import { runIntake } from "../src/rules";
import bills from "../public/data/bills.json";
import vendorRegister from "../public/data/vendor-register.json";
import postedRegister from "../public/data/posted-register.json";
import fxTable from "../public/data/fx-table.json";
import goldenSet from "../public/data/golden-set.json";

describe("golden-set action agreement (non-gating)", () => {
  it("reports the TS-mirror vs golden-set agreement rate", () => {
    const { bills: processed } = runIntake(
      bills as Array<{ bill_id: string; bill_text: string }>,
      vendorRegister as any,
      postedRegister as any,
      fxTable as any
    );
    const byId = new Map(processed.map((b) => [b.bill_id, b]));
    let agree = 0;
    const mismatches: string[] = [];
    for (const g of goldenSet as Array<{
      bill_id: string;
      expected_action: string;
      vendor_id: string;
      invoice_number: string | null;
      invoice_date: string;
      total_cad: number;
    }>) {
      const p = byId.get(g.bill_id);
      const got = p?.action ?? "(missing)";
      const vendorOk = p?.vendor_id === g.vendor_id;
      const totalOk =
        p != null && Math.abs(p.total_cad - g.total_cad) < 0.005;
      if (got === g.expected_action && vendorOk && totalOk) {
        agree++;
      } else {
        mismatches.push(
          `${g.bill_id}: expected ${g.expected_action} / vendor ${g.vendor_id} / $${g.total_cad}` +
            ` — got ${got} / vendor ${p?.vendor_id} / $${p?.total_cad} [flags: ${p?.flags.join(",")}]`
        );
      }
    }
    const rate = (agree / (goldenSet as unknown[]).length) * 100;
    console.log(
      `\n  golden-set agreement: ${agree}/${(goldenSet as unknown[]).length} = ${rate.toFixed(1)}%`
    );
    for (const m of mismatches) console.log(`  MISMATCH  ${m}`);
    // Sanity: every golden bill was processed and labeled with a known action.
    expect(byId.size).toBe(120);
    for (const g of goldenSet as Array<{ bill_id: string }>) {
      expect(byId.has(g.bill_id)).toBe(true);
    }
  });
});
