"""LangGraph node functions for the InTray intake desk.

Every node is a thin deterministic wrapper around src/intray/rules.py —
zero LLM calls anywhere in the pipeline. The batch-level split-dodge scan
runs in `split_detect_node` over the `batch_invoices` carried in state, so
each bill's graph run still sees the full replay window.
"""

from . import rules


def intake_node(state):
    return {"replay_date": state.get("replay_date", "2026-11-02")}


def extract_node(state):
    extracted = rules.extract(state["bill"]["bill_text"])
    return {"extracted": extracted}


def normalize_node(state):
    ext = state["extracted"]
    alias = rules.normalize_vendor(ext["vendor_name"], state["vendor_register"])
    vendor = None
    if alias["resolved"]:
        vendor = next(
            v for v in state["vendor_register"] if v["vendor_id"] == alias["vendor_id"]
        )
    header_total = ext.get("total") if ext.get("currency") == "CAD" else ext.get("total_foreign")
    total_cad = rules.to_cad(header_total or 0.0, ext.get("currency"), state["fx"])
    return {
        "alias": alias,
        "vendor_id": alias["vendor_id"],
        "vendor": vendor,
        "total_cad": total_cad,
        "batch_invoice": {
            "bill_id": state["bill"]["bill_id"],
            "vendor_id": alias["vendor_id"],
            "invoice_date": ext.get("invoice_date"),
            "po": ext.get("po"),
            "total_cad": total_cad,
        },
    }


def dedupe_node(state):
    result = rules.check_dedupe(
        state.get("vendor_id"),
        state["extracted"].get("invoice_number"),
        state.get("total_cad"),
        state["extracted"].get("invoice_date"),
        state.get("posted_register"),
    )
    return {"dedupe": result}


def validate_node(state):
    ext = state["extracted"]
    flag_details = rules.validate_bill(ext, state.get("vendor"), state.get("total_cad"),
                                       state.get("replay_date", "2026-11-02"))
    flags = [f["flag"] for f in flag_details]
    total_cad = state.get("total_cad")
    for f in flag_details:
        if f["flag"] == "V2_UNFOOTED_TOTAL":
            # book the true (corrected) total, converted to CAD
            total_cad = rules.to_cad(f["corrected_total"], ext.get("currency"), state["fx"])
    return {"flags": flags, "flag_details": flag_details, "total_cad": total_cad}


def split_detect_node(state):
    scan = rules.detect_split(state.get("batch_invoices", []))
    flags = list(state.get("flags", []))
    split_info = None
    if state["bill"]["bill_id"] in scan.get("flagged_bill_ids", []):
        flags.append("SPLIT_DODGE")
        split_info = {
            "cluster_size": scan["cluster_size"],
            "cluster_sum": scan["cluster_sum"],
            "window_days": scan["window_days"],
        }
    return {"flags": flags, "split_info": split_info, "split_scan": scan}


def route_node(state):
    tier, action = rules.route(state.get("total_cad"), state.get("flags"), state.get("dedupe"))
    return {"tier": tier, "action": action}


def draft_node(state):
    ext = state["extracted"]
    total = state.get("total_cad")
    reason = _reasoning(state)
    draft = (
        f"Bill {state['bill']['bill_id']}: {ext.get('vendor_name')} "
        f"INV {ext.get('invoice_number') or 'n/a'} dated {ext.get('invoice_date')} "
        f"for ${total:,.2f} CAD -> {state.get('tier')} / {state.get('action')}. {reason}"
    )
    return {"draft": draft, "reasoning": reason}


def gate_node(state):
    # Deterministic human gate: record the routed action as the gate decision.
    # (A live deployment would pause AUTO_POST/HOLD items here for approval.)
    return {"gate_decision": state.get("action"), "gated": True}


def _reasoning(state):
    flags = state.get("flags", [])
    dedupe = state.get("dedupe", {})
    total = state.get("total_cad")
    if dedupe.get("match_type") == "D1_EXACT":
        m = dedupe.get("matched_posted", {})
        return (f"D1 exact resubmission of posted {m.get('invoice_number')} "
                f"({m.get('vendor_id')}); held.")
    if dedupe.get("match_type") == "D2_NEAR":
        return (f"D2 near-duplicate: total within {dedupe.get('total_diff_pct')}% "
                f"and {dedupe.get('date_diff_days')}d of a posted bill; held.")
    if "V2_UNFOOTED_TOTAL" in flags:
        d = next(f for f in state.get("flag_details", []) if f["flag"] == "V2_UNFOOTED_TOTAL")
        return (f"Header total ${d['header_total']:,.2f} does not foot "
                f"(lines+tax ${d['corrected_total']:,.2f}); correcting.")
    if "V3_MISSING_PO" in flags:
        return "Vendor requires a PO but none is on the bill; requesting PO."
    if "SPLIT_DODGE" in flags:
        s = state.get("split_info", {}) or {}
        return (f"Split-dodge: {s.get('cluster_size')} invoices on one PO inside "
                f"{s.get('window_days')}d summing ${s.get('cluster_sum', 0):,.2f}; escalated.")
    if "V1_FUTURE_DATED" in flags:
        return "Invoice date is after the replay date; manager review."
    if "V4_ROUND_NUMBER" in flags:
        return "Round-number total flagged (low weight); routed by amount tier."
    if state.get("tier") == "AUTO-INTAKE":
        return f"${total:,.2f} under $1,000 with no flags; auto-intake ready."
    if state.get("tier") == "MANAGER":
        return f"${total:,.2f} in the $1,000-$5,000 band; manager approval."
    return f"${total:,.2f} over $5,000; director approval."
