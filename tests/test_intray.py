"""InTray contract tests.

1. The 14 hand-computed vectors in data/test-vectors.json — every `expected`
   key must match the Python rules function output EXACTLY (totals to 2dp,
   dates ISO). This is the shared contract the TS vitest also asserts.
2. Golden-set agreement — recompute eval metrics from pipeline-results.json
   independently and assert they equal the recorded values in eval.json.
   Honest by construction: whatever the pipeline measures is what we assert.
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from intray import rules  # noqa: E402

DATA = REPO / "data"
VECTORS = json.loads((DATA / "test-vectors.json").read_text())


def assert_expected(actual, expected):
    for key, want in expected.items():
        assert key in actual, f"missing key {key!r} in {actual!r}"
        got = actual[key]
        assert got == want, f"key {key!r}: got {got!r}, want {want!r}"


def test_vector_extract():
    for v in [x for x in VECTORS if x["rule"] == "extract"]:
        got = rules.extract(v["input"]["bill_text"])
        assert_expected(got, v["expected"])


def test_vector_normalize():
    for v in [x for x in VECTORS if x["rule"] == "normalize"]:
        got = rules.normalize_vendor(v["input"]["vendor_text"], v["input"]["vendor_register"])
        assert_expected(got, v["expected"])


def test_vector_dedupe():
    for v in [x for x in VECTORS if x["rule"] == "dedupe"]:
        b = v["input"]["bill"]
        got = rules.check_dedupe(
            b.get("vendor_id"), b.get("invoice_number"), b.get("total_cad"),
            b.get("invoice_date"), v["input"]["posted_register"],
        )
        assert_expected(got, v["expected"])


def test_vector_validate():
    for v in [x for x in VECTORS if x["rule"] == "validate"]:
        i = v["input"]
        if v["id"] == "VALID-01":
            got = rules.check_future_dated(i["invoice_date"], i["replay_date"])
        elif v["id"] == "VALID-02":
            got = rules.check_unfooted(i["header_total"], i["line_items"])
        elif v["id"] == "VALID-03":
            got = rules.check_missing_po(i["po"], i["vendor"])
        elif v["id"] == "VALID-04":
            got = rules.check_round_number(i["total_cad"])
        else:
            raise AssertionError(f"unknown validate vector {v['id']}")
        assert_expected(got, v["expected"])


def test_vector_split_detect():
    for v in [x for x in VECTORS if x["rule"] == "split_detect"]:
        got = rules.detect_split(v["input"]["invoices"])
        assert_expected(got, v["expected"])


def test_vector_route():
    for v in [x for x in VECTORS if x["rule"] == "route"]:
        fx = v["input"]["fx_table"]
        got = []
        for b in v["input"]["bills"]:
            total_cad = rules.to_cad(b["total"], b["currency"], fx)
            tier, action = rules.route(total_cad, b["flags"], None)
            got.append({"bill_id": b["bill_id"], "route": tier,
                        "action": action, "total_cad": total_cad})
        for g, w in zip(got, v["expected"]["results"]):
            assert_expected(g, w)


# --------------------------------------------------------------------------
# golden-set agreement (honest: asserts recorded eval.json values)
# --------------------------------------------------------------------------

TOTAL_RX = re.compile(r"^\s*Total:\s*(?:US\$|\u20ac|\u00a3|\$)\s*([\d,]+\.\d{2})\s*$", re.M)


def _recompute():
    pipeline = json.loads((DATA / "outputs" / "pipeline-results.json").read_text())
    golden = json.loads((DATA / "golden-set.json").read_text())
    bills = json.loads((DATA / "outputs" / "bills.json").read_text())
    fx = json.loads((DATA / "outputs" / "fx-table.json").read_text())
    bill_text = {b["bill_id"]: b["bill_text"] for b in bills}
    by_id = {r["bill_id"]: r for r in pipeline["bills"]}

    ext_hits = {"vendor": 0, "invoice_number": 0, "invoice_date": 0, "total": 0}
    correct = 0
    for g in golden:
        r = by_id[g["bill_id"]]
        printed = float(TOTAL_RX.search(bill_text[g["bill_id"]]).group(1).replace(",", ""))
        printed_cad = rules.to_cad(printed, r["extracted"]["currency"], fx)
        got_cad = rules.to_cad(r["extracted"]["header_total"], r["extracted"]["currency"], fx)
        checks = {
            "vendor": r["vendor_id"] == g["vendor_id"],
            "invoice_number": r["extracted"]["invoice_number"] == g["invoice_number"],
            "invoice_date": r["extracted"]["invoice_date"] == g["invoice_date"],
            "total": abs(got_cad - printed_cad) < 0.005,
        }
        for k, ok in checks.items():
            ext_hits[k] += ok
        correct += r["action"] == g["expected_action"]
    n = len(golden)
    return (
        {k: round(v / n, 4) for k, v in ext_hits.items()},
        round(correct / n, 4),
    )


def test_golden_agreement_matches_eval_json():
    eval_rec = json.loads((DATA / "outputs" / "eval.json").read_text())
    ext_acc, routing_acc = _recompute()
    assert ext_acc == eval_rec["extraction_accuracy"], (
        f"extraction accuracy drifted: recomputed {ext_acc} vs recorded "
        f"{eval_rec['extraction_accuracy']}")
    assert routing_acc == eval_rec["routing_accuracy"], (
        f"routing accuracy drifted: recomputed {routing_acc} vs recorded "
        f"{eval_rec['routing_accuracy']}")
    # every recorded mismatch must still be a real mismatch
    pipeline = json.loads((DATA / "outputs" / "pipeline-results.json").read_text())
    by_id = {r["bill_id"]: r for r in pipeline["bills"]}
    golden = {g["bill_id"]: g for g in json.loads((DATA / "golden-set.json").read_text())}
    for m in eval_rec["mismatches"]:
        if m["kind"] == "routing":
            assert by_id[m["bill_id"]]["action"] != golden[m["bill_id"]]["expected_action"]
