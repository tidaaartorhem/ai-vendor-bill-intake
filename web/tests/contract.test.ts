/**
 * Contract suite: every test vector in data/test-vectors.json must be
 * reproduced EXACTLY by the TypeScript rules mirror (2-decimal totals,
 * ISO dates). This is the same contract the Python engine is held to.
 */
import { describe, expect, it } from "vitest";
import {
  checkFutureDated,
  checkMissingPO,
  checkRoundNumber,
  checkUnfooted,
  dedupeBill,
  detectSplitDodge,
  extractBill,
  normalizeVendor,
  routeBills,
} from "../src/rules";
import vectors from "../src/test-vectors.json";

interface Vector {
  id: string;
  rule: string;
  description: string;
  input: any;
  expected: any;
}

function runVector(v: Vector): unknown {
  switch (v.rule) {
    case "extract":
      return extractBill(v.input.bill_text);
    case "normalize":
      return normalizeVendor(v.input.vendor_text, v.input.vendor_register);
    case "dedupe":
      return dedupeBill(v.input.bill, v.input.posted_register);
    case "validate":
      if (v.id.startsWith("VALID-01"))
        return checkFutureDated(v.input.invoice_date, v.input.replay_date);
      if (v.id.startsWith("VALID-02"))
        return checkUnfooted(v.input);
      if (v.id.startsWith("VALID-03"))
        return checkMissingPO(v.input.po, v.input.vendor);
      if (v.id.startsWith("VALID-04"))
        return checkRoundNumber(v.input.total_cad);
      throw new Error(`unknown validate vector ${v.id}`);
    case "split_detect":
      return detectSplitDodge(v.input.invoices);
    case "route":
      return routeBills(v.input);
    default:
      throw new Error(`unknown rule ${v.rule}`);
  }
}

describe("test-vector contract (data/test-vectors.json)", () => {
  for (const v of vectors as Vector[]) {
    it(`${v.id} — ${v.description}`, () => {
      expect(runVector(v)).toEqual(v.expected);
    });
  }
});
