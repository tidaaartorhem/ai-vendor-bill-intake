#!/usr/bin/env python3
"""Run the InTray intake graph over the 120-bill replay feed.

Writes:
  data/outputs/pipeline-results.json — per-bill outcomes + summary + vendors
  data/outputs/eval.json             — golden-set eval (honest numbers)

Deterministic: fixed replay date 2026-11-02, no randomness, zero LLM calls.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from intray import build_graph, rules  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"
OUT = DATA / "outputs"
REPLAY_DATE = "2026-11-02"

TOTAL_RX = re.compile(r"^\s*Total:\s*(?:US\$|\u20ac|\u00a3|\$)\s*([\d,]+\.\d{2})\s*$", re.M)


def load(name):
    return json.loads((OUT / name).read_text())


def main():
    bills = load("bills.json")
    vendors = load("vendor-register.json")
    posted = load("posted-register.json")
    fx = load("fx-table.json")
    golden = json.loads((DATA / "golden-set.json").read_text())

    # Pass 1: extract + normalize every bill so split detection sees the batch.
    prepped = []
    for bill in bills:
        ext = rules.extract(bill["bill_text"])
        alias = rules.normalize_vendor(ext["vendor_name"], vendors)
        header = ext.get("total") if ext.get("currency") == "CAD" else ext.get("total_foreign")
        total_cad = rules.to_cad(header or 0.0, ext.get("currency"), fx)
        prepped.append((bill, ext, alias, total_cad))
    batch_invoices = [
        {
            "bill_id": bill["bill_id"],
            "vendor_id": alias["vendor_id"],
            "invoice_date": ext.get("invoice_date"),
            "po": ext.get("po"),
            "total_cad": total_cad,
        }
        for bill, ext, alias, total_cad in prepped
    ]

    # Pass 2: run the graph per bill.
    app = build_graph()
    results = []
    for bill, ext, alias, _ in prepped:
        state = {
            "bill": bill,
            "replay_date": REPLAY_DATE,
            "vendor_register": vendors,
            "posted_register": posted,
            "fx": fx,
            "batch_invoices": batch_invoices,
        }
        out = app.invoke(state)
        results.append({
            "bill_id": bill["bill_id"],
            "received_at": bill.get("received_at"),
            "seed_flags": bill.get("seed_flags", []),
            "extracted": {
                "vendor_name": out["extracted"]["vendor_name"],
                "invoice_number": out["extracted"]["invoice_number"],
                "invoice_date": out["extracted"]["invoice_date"],
                "po": out["extracted"]["po"],
                "currency": out["extracted"]["currency"],
                "n_line_items": len(out["extracted"]["line_items"]),
                "header_total": (out["extracted"].get("total")
                                 if out["extracted"].get("currency") == "CAD"
                                 else out["extracted"].get("total_foreign")),
            },
            "vendor_id": out.get("vendor_id"),
            "vendor_canonical": out.get("alias", {}).get("canonical_name"),
            "total_cad": out.get("total_cad"),
            "dedupe": out.get("dedupe", {}).get("dedupe"),
            "dedupe_detail": {k: v for k, v in out.get("dedupe", {}).items()},
            "flags": out.get("flags", []),
            "flag_details": out.get("flag_details", []),
            "tier": out.get("tier"),
            "action": out.get("action"),
            "reasoning": out.get("reasoning"),
        })

    by_id = {r["bill_id"]: r for r in results}
    by_action, by_tier = {}, {}
    for r in results:
        by_action[r["action"]] = by_action.get(r["action"], 0) + 1
        by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    auto = [r for r in results if r["action"] == "AUTO_POST"]
    summary = {
        "total_bills": len(results),
        "replay_date": REPLAY_DATE,
        "by_action": by_action,
        "by_tier": by_tier,
        "auto_intake_ready": len(auto),
        "duplicates_caught": by_action.get("HOLD_DUPLICATE", 0),
        "split_dodges": sum(1 for r in results if "SPLIT_DODGE" in r["flags"]),
        "intake_value_cad": round(sum(r["total_cad"] for r in auto), 2),
        "missing_po_holds": by_action.get("REQUEST_PO", 0),
    }

    vendors_out = {}
    for r in results:
        vid = r["vendor_id"] or "UNRESOLVED"
        v = vendors_out.setdefault(vid, {
            "canonical_name": r["vendor_canonical"],
            "bill_count": 0,
            "variant_spellings": [],
        })
        v["bill_count"] += 1
        spelling = r["extracted"]["vendor_name"]
        if spelling not in v["variant_spellings"]:
            v["variant_spellings"].append(spelling)

    pipeline = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "replay_date": REPLAY_DATE,
        "bills": results,
        "summary": summary,
        "vendors": vendors_out,
    }
    (OUT / "pipeline-results.json").write_text(json.dumps(pipeline, indent=2, sort_keys=True))

    # ---- eval on the golden set ----
    bill_text = {b["bill_id"]: b["bill_text"] for b in bills}
    mismatches = []
    ext_correct = {"vendor": 0, "invoice_number": 0, "invoice_date": 0, "total": 0}
    y_true, y_pred = [], []

    for g in golden:
        r = by_id[g["bill_id"]]
        # Extraction truth: golden labels, except total = the PRINTED figure
        # (for the 2 unfooted bills the printed total is wrong by design —
        # extracting it correctly still counts as correct).
        printed = float(TOTAL_RX.search(bill_text[g["bill_id"]]).group(1).replace(",", ""))
        printed_cad = rules.to_cad(printed, r["extracted"]["currency"], fx)
        got_total_cad = rules.to_cad(
            r["extracted"]["header_total"], r["extracted"]["currency"], fx)
        checks = {
            "vendor": (r["vendor_id"], g["vendor_id"]),
            "invoice_number": (r["extracted"]["invoice_number"], g["invoice_number"]),
            "invoice_date": (r["extracted"]["invoice_date"], g["invoice_date"]),
            "total": (got_total_cad, printed_cad),
        }
        for field, (got, want) in checks.items():
            ok = (got == want) if not isinstance(want, float) else abs(got - want) < 0.005
            if ok:
                ext_correct[field] += 1
            else:
                mismatches.append({
                    "bill_id": g["bill_id"], "kind": "extraction",
                    "field": field, "expected": want, "got": got,
                })
        y_true.append(g["expected_action"])
        y_pred.append(r["action"])
        if r["action"] != g["expected_action"]:
            mismatches.append({
                "bill_id": g["bill_id"], "kind": "routing",
                "expected": g["expected_action"], "got": r["action"],
                "note": r["reasoning"],
            })

    n = len(golden)
    extraction_accuracy = {k: round(v / n, 4) for k, v in ext_correct.items()}
    actions = sorted(set(y_true) | set(y_pred))
    per_action = {}
    for a in actions:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == a and p == a)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != a and p == a)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == a and p != a)
        per_action[a] = {
            "precision": round(tp / (tp + fp), 4) if tp + fp else 0.0,
            "recall": round(tp / (tp + fn), 4) if tp + fn else 0.0,
            "support": sum(1 for t in y_true if t == a),
        }
    routing_accuracy = round(sum(1 for t, p in zip(y_true, y_pred) if t == p) / n, 4)

    # name-variant resolution on the 6 seeded variants (B001-B006)
    variant_hits = 0
    for bid in ["B001", "B002", "B003", "B004", "B005", "B006"]:
        ext = rules.extract(bill_text[bid])
        if rules.normalize_vendor(ext["vendor_name"], vendors)["resolved"]:
            variant_hits += 1

    eval_out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "replay_date": REPLAY_DATE,
        "n_golden": n,
        "extraction_accuracy": extraction_accuracy,
        "alias_accuracy": extraction_accuracy["vendor"],
        "name_variant_resolution": {"resolved": variant_hits, "total": 6},
        "routing_accuracy": routing_accuracy,
        "routing_per_action": per_action,
        "mismatches": mismatches,
    }
    (OUT / "eval.json").write_text(json.dumps(eval_out, indent=2, sort_keys=True))

    print(json.dumps({"summary": summary, "eval": {
        "extraction_accuracy": extraction_accuracy,
        "alias_accuracy": extraction_accuracy["vendor"],
        "name_variant_resolution": {"resolved": variant_hits, "total": 6},
        "routing_accuracy": routing_accuracy,
        "mismatches": len(mismatches),
    }}, indent=2))


if __name__ == "__main__":
    main()
