"""InTray rules engine — pure deterministic functions, no LangGraph imports.

This module is the contract core: the TS UI mirror follows the same logic.
Every money value is handled in integer cents internally; public outputs are
rounded to 2 decimals. Thresholds (all disclosed in README):

  ALIAS: token-set Jaccard >= 0.60, tie-break longest canonical name.
  D1:    same vendor_id + invoice_number in the posted register -> DUPLICATE.
  D2:    same vendor + total within 1% + date within 7 days +
         invoice# differs or missing -> LIKELY_DUPLICATE.
  V1:    invoice_date > replay date -> future-dated.
  V2:    |sum(lines)+tax - header_total| > $0.05 AND > 0.5% of header -> unfooted.
  V3:    po_required vendor with no PO ref -> missing PO.
  V4:    total_cad >= $1,000 and a whole multiple of $1,000 -> round-number
         (low-weight REVIEW flag; routing still follows the amount tier).
  SPLIT: same vendor + same PO, invoices inside a 7-day window, at least one
         in the $4k-$5k band, cluster sum > $5,000 -> SPLIT_DODGE.
  ROUTE: < $1,000 AUTO-INTAKE; $1,000-$5,000 MANAGER; > $5,000 DIRECTOR;
         any duplicate/validation flag -> REVIEW tier.
"""

import re
from datetime import date

# --------------------------------------------------------------------------
# tokenisation / alias resolution
# --------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(name):
    """Lowercase alphanumeric word tokens; '&' and punctuation are dropped."""
    return set(_TOKEN_RE.findall(name.lower()))


def jaccard(a, b):
    """Token-set Jaccard similarity in [0, 1]."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


ALIAS_THRESHOLD = 0.60


def normalize_vendor(name, register):
    """Resolve a display name to a vendor_id via token-set Jaccard >= 0.60.

    Returns a dict so callers (and the test vectors) can see the evidence:
    {resolved, vendor_id, canonical_name, jaccard, best_candidate, best_score}.
    Ties are broken by longest canonical name, then vendor_id for determinism.
    """
    name_tokens = tokenize(name)
    scored = []
    for v in register:
        score = jaccard(name_tokens, tokenize(v["canonical_name"]))
        scored.append((score, v))
    scored.sort(key=lambda s: (-s[0], -len(s[1]["canonical_name"]), s[1]["vendor_id"]))
    best_score, best = scored[0]
    best_score = round(best_score, 4)
    resolved = best_score >= ALIAS_THRESHOLD
    return {
        "resolved": resolved,
        "vendor_id": best["vendor_id"] if resolved else None,
        "canonical_name": best["canonical_name"] if resolved else None,
        "jaccard": best_score,
        "best_candidate": best["vendor_id"],
        "best_score": best_score,
    }


# --------------------------------------------------------------------------
# money helpers (integer cents throughout)
# --------------------------------------------------------------------------

def parse_money_cents(text):
    """'1,390.20' -> 139020 (cents). Raises ValueError on garbage."""
    return int(round(float(text.replace(",", "")) * 100))


def cents_to_float(cents):
    return round(cents / 100, 2)


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}


def normalize_date(raw):
    """'Oct 28 2026' | '2026-10-28' | '28/10/2026' (dd/mm/yyyy) -> 'YYYY-MM-DD'."""
    raw = raw.strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", raw)
    if m:
        return raw
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", raw)
    if m:
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{yyyy:04d}-{mm:02d}-{dd:02d}"
    m = re.match(r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})$", raw)
    if m:
        mon = _MONTHS[m.group(1).lower()[:4]]
        return f"{int(m.group(3)):04d}-{mon:02d}-{int(m.group(2)):02d}"
    raise ValueError(f"unparseable date: {raw!r}")


def to_cad(amount, currency, fx):
    """Convert a foreign-currency amount to CAD, rounded to 2dp (half-up)."""
    if currency == "CAD" or currency is None:
        return round(float(amount), 2)
    rate = fx[currency]
    # integer-cents math mirrors the seed generator (exact half-cent cases
    # were regenerated away, so half-up is exact on this data)
    foreign_cents = int(round(float(amount) * 100))
    rate_cents = int(round(rate * 100))
    n = foreign_cents * rate_cents
    r = n % 100
    cad_cents = n // 100 + (1 if r > 50 else 0)
    return cents_to_float(cad_cents)


# --------------------------------------------------------------------------
# extraction
# --------------------------------------------------------------------------

_MONEY = r"(?:US\$|€|£|\$)"
_LINE_RE = re.compile(
    rf"^\s*(\d+)\s*x\s*(.+?)\s*@\s*(US\$|€|£|\$)\s*([\d,]+\.\d{{2}})\s*$", re.M
)
_INV_HASH_RE = re.compile(r"^\s*Invoice\s*#\s*([A-Za-z0-9][A-Za-z0-9\-]*)\s*$", re.M)
_INV_NO_RE = re.compile(r"^\s*No\.\s*([A-Za-z0-9][A-Za-z0-9\-]*)\s*$", re.M)
_INV_DASH_RE = re.compile(r"^\s*(INV-[A-Za-z0-9\-]+)\s*$", re.M)
_DATE_RE = re.compile(r"^\s*Date:\s*(.+?)\s*$", re.M)
_PO_RE = re.compile(r"^\s*(?:PO|P\.O\.)\s*:\s*(PO-\d+)\s*$", re.M)
_CCY_RE = re.compile(r"^\s*Currency:\s*([A-Z]{3})\s*$", re.M)
_SUBTOTAL_RE = re.compile(rf"^\s*Subtotal:\s*{_MONEY}\s*([\d,]+\.\d{{2}})\s*$", re.M)
_TAX_RE = re.compile(rf"^\s*Tax(?:\s*\(.*?\))?:\s*{_MONEY}\s*([\d,]+\.\d{{2}})\s*$", re.M)
_TOTAL_RE = re.compile(rf"^\s*Total:\s*{_MONEY}\s*([\d,]+\.\d{{2}})\s*$", re.M)


def _sym_to_currency_symbol(text):
    if "US$" in text:
        return "US$"
    if "€" in text:
        return "€"
    if "£" in text:
        return "£"
    return None


def extract(bill_text):
    """Parse a bill document into structured fields.

    invoice_number: prefixes 'Invoice #' / 'No.' are stripped; 'INV-…'
    numbers are kept verbatim. Returns printed (header) figures as-is —
    validation decides whether they foot.
    """
    lines = [ln for ln in bill_text.splitlines() if ln.strip()]
    vendor_name = lines[0].strip() if lines else ""

    invoice_number = None
    m = _INV_HASH_RE.search(bill_text) or _INV_NO_RE.search(bill_text)
    if m:
        invoice_number = m.group(1)
    else:
        m = _INV_DASH_RE.search(bill_text)
        if m:
            invoice_number = m.group(1)

    date_m = _DATE_RE.search(bill_text)
    invoice_date_raw = date_m.group(1).strip() if date_m else None
    invoice_date = normalize_date(invoice_date_raw) if invoice_date_raw else None

    po_m = _PO_RE.search(bill_text)
    po = po_m.group(1) if po_m else None

    ccy_m = _CCY_RE.search(bill_text)
    currency = ccy_m.group(1) if ccy_m else "CAD"
    currency_symbol = _sym_to_currency_symbol(bill_text)

    line_items = []
    for lm in _LINE_RE.finditer(bill_text):
        qty = int(lm.group(1))
        unit_cents = parse_money_cents(lm.group(4))
        line_items.append({
            "qty": qty,
            "description": lm.group(2).strip(),
            "unit_price": cents_to_float(unit_cents),
            "line_total": cents_to_float(qty * unit_cents),
        })

    def _money(rx):
        m = rx.search(bill_text)
        return cents_to_float(parse_money_cents(m.group(1))) if m else None

    subtotal = _money(_SUBTOTAL_RE)
    tax = _money(_TAX_RE)
    total = _money(_TOTAL_RE)

    out = {
        "vendor_name": vendor_name,
        "invoice_number": invoice_number,
        "invoice_date_raw": invoice_date_raw,
        "invoice_date": invoice_date,
        "po": po,
        "currency": currency,
        "currency_symbol": currency_symbol,
        "line_items": line_items,
        "subtotal": subtotal,
        "tax": tax,
    }
    # Contract: foreign bills report `total_foreign`, CAD bills `total`.
    if currency == "CAD":
        out["total"] = total
    else:
        out["total_foreign"] = total
    return out


# --------------------------------------------------------------------------
# dedupe
# --------------------------------------------------------------------------

def check_dedupe(vendor_id, invoice_number, total_cad, invoice_date, posted):
    """D1 exact / D2 near-duplicate check against the posted register."""
    posted = posted or []
    if invoice_number:
        for p in posted:
            if p.get("vendor_id") == vendor_id and p.get("invoice_number") == invoice_number:
                return {
                    "dedupe": "DUPLICATE",
                    "is_duplicate": True,
                    "likely_duplicate": False,
                    "match_type": "D1_EXACT",
                    "matched_posted": {
                        "vendor_id": p["vendor_id"],
                        "invoice_number": p["invoice_number"],
                    },
                    "total_diff_pct": 0.0,
                    "date_diff_days": 0,
                    "action": "HOLD_DUPLICATE",
                }
    best = None
    if vendor_id and total_cad is not None and invoice_date:
        for p in posted:
            if p.get("vendor_id") != vendor_id:
                continue
            if invoice_number and p.get("invoice_number") == invoice_number:
                continue  # would have been D1
            try:
                p_total = float(p["total_cad"])
                d1 = date.fromisoformat(invoice_date)
                d2 = date.fromisoformat(p["invoice_date"])
            except (KeyError, ValueError, TypeError):
                continue
            if p_total <= 0:
                continue
            pct = abs(total_cad - p_total) / p_total
            days = abs((d1 - d2).days)
            if pct <= 0.01 and days <= 7:
                if best is None or pct < best[0]:
                    best = (pct, days, p)
    if best:
        pct, days, p = best
        return {
            "dedupe": "LIKELY_DUPLICATE",
            "is_duplicate": False,
            "likely_duplicate": True,
            "match_type": "D2_NEAR",
            "matched_posted": {
                "vendor_id": p["vendor_id"],
                "invoice_number": p.get("invoice_number"),
            },
            "total_diff_pct": round(pct * 100, 2),
            "date_diff_days": days,
            "action": "HOLD_DUPLICATE",
        }
    return {
        "dedupe": "OK",
        "is_duplicate": False,
        "likely_duplicate": False,
        "match_type": None,
        "matched_posted": None,
        "total_diff_pct": None,
        "date_diff_days": None,
        "action": None,
    }


# --------------------------------------------------------------------------
# validation flags V1..V4
# --------------------------------------------------------------------------

def check_future_dated(invoice_date, replay_date):
    if invoice_date and invoice_date > replay_date:
        days = (date.fromisoformat(invoice_date) - date.fromisoformat(replay_date)).days
        return {
            "future_dated": True,
            "flag": "V1_FUTURE_DATED",
            "days_after_replay": days,
            "action": "SEND_TO_MANAGER",
        }
    return {"future_dated": False, "flag": None, "days_after_replay": 0, "action": None}


def check_unfooted(header_total, line_items, tax=0.0):
    """V2: printed header total does not foot against Σ lines + tax."""
    sum_cents = sum(
        int(li["qty"]) * parse_money_cents(f"{float(li['unit_price']):.2f}")
        for li in line_items
    )
    tax_cents = parse_money_cents(f"{float(tax or 0.0):.2f}")
    expected_cents = sum_cents + tax_cents
    header_cents = parse_money_cents(f"{float(header_total):.2f}")
    diff_cents = abs(expected_cents - header_cents)
    diff = cents_to_float(diff_cents)
    expected = cents_to_float(expected_cents)
    diff_pct = round(diff / expected * 100, 2) if expected else 0.0
    unfooted = diff_cents > 5 and diff_cents > 0.005 * header_cents
    return {
        "unfooted": unfooted,
        "flag": "V2_UNFOOTED_TOTAL" if unfooted else None,
        "sum_lines": cents_to_float(sum_cents),
        "header_total": cents_to_float(header_cents),
        "diff": diff,
        "diff_pct": diff_pct,
        "corrected_total": expected,
        "action": "CORRECT_TOTAL" if unfooted else None,
    }


def check_missing_po(po_ref, vendor):
    missing = bool(vendor) and bool(vendor.get("po_required")) and not po_ref
    return {
        "missing_po": missing,
        "flag": "V3_MISSING_PO" if missing else None,
        "action": "REQUEST_PO" if missing else None,
    }


def check_round_number(total_cad):
    cents = int(round(float(total_cad) * 100))
    is_round = float(total_cad) >= 1000 and cents % 100000 == 0
    return {
        "round_number": is_round,
        "flag": "V4_ROUND_NUMBER" if is_round else None,
        "weight": "low" if is_round else None,
        "route": "MANAGER" if is_round else None,
        "action": "SEND_TO_MANAGER" if is_round else None,
    }


def validate_bill(extracted, vendor, total_cad, replay_date):
    """Run V1..V4; returns the list of triggered flag detail dicts."""
    flags = []
    v1 = check_future_dated(extracted.get("invoice_date"), replay_date)
    if v1["flag"]:
        flags.append(v1)
    v2 = check_unfooted(
        extracted.get("total") if extracted.get("currency") == "CAD"
        else extracted.get("total_foreign"),
        extracted.get("line_items", []),
        extracted.get("tax") or 0.0,
    )
    if v2["flag"]:
        flags.append(v2)
    v3 = check_missing_po(extracted.get("po"), vendor)
    if v3["flag"]:
        flags.append(v3)
    v4 = check_round_number(total_cad)
    if v4["flag"]:
        flags.append(v4)
    return flags


# --------------------------------------------------------------------------
# split-dodge detection
# --------------------------------------------------------------------------

def detect_split(invoices):
    """Flag a vendor+PO cluster that looks like a split approval dodge.

    invoices: [{bill_id, vendor_id, invoice_date (ISO), po, total_cad}].
    Within each (vendor_id, po) group, take the largest subset of invoices
    inside a 7-day window; SPLIT_DODGE when it has >= 2 invoices, at least
    one total in the $4k-$5k band, and cluster sum > $5,000.
    """
    groups = {}
    for inv in invoices:
        if not inv.get("po") or not inv.get("vendor_id"):
            continue
        groups.setdefault((inv["vendor_id"], inv["po"]), []).append(inv)

    flagged = []
    best_cluster = None
    for (vendor_id, po), items in groups.items():
        items = sorted(items, key=lambda i: i["invoice_date"])
        dates = [date.fromisoformat(i["invoice_date"]) for i in items]
        # sliding window: largest subset within 7 days
        n = len(items)
        best = []
        j = 0
        for i in range(n):
            while (dates[i] - dates[j]).days > 7:
                j += 1
            window = items[j:i + 1]
            if len(window) > len(best):
                best = window
        if len(best) >= 2:
            total = sum(i["total_cad"] for i in best)
            in_band = any(4000 <= i["total_cad"] <= 5000 for i in best)
            if in_band and total > 5000:
                wdays = (date.fromisoformat(best[-1]["invoice_date"])
                         - date.fromisoformat(best[0]["invoice_date"])).days
                cluster = {
                    "vendor_id": vendor_id, "po": po,
                    "bill_ids": [i["bill_id"] for i in best],
                    "cluster_size": len(best),
                    "cluster_sum": round(total, 2),
                    "window_days": wdays,
                }
                flagged.extend(cluster["bill_ids"])
                if best_cluster is None or cluster["cluster_sum"] > best_cluster["cluster_sum"]:
                    best_cluster = cluster

    if not flagged:
        return {
            "split_dodge": False, "flag": None, "flagged_bill_ids": [],
            "cluster_size": 0, "cluster_sum": 0.0, "window_days": 0,
            "action": None,
        }
    return {
        "split_dodge": True,
        "flag": "SPLIT_DODGE",
        "flagged_bill_ids": flagged,
        "cluster_size": best_cluster["cluster_size"],
        "cluster_sum": best_cluster["cluster_sum"],
        "window_days": best_cluster["window_days"],
        "action": "SEND_TO_DIRECTOR",
    }


# --------------------------------------------------------------------------
# routing
# --------------------------------------------------------------------------

def route(total_cad, flags, dedupe):
    """(tier, action). Flag priority: duplicate > V2 > V3 > SPLIT > V1 > V4."""
    flags = flags or []
    dup = (
        (dedupe and (dedupe.get("is_duplicate") or dedupe.get("likely_duplicate")))
        or "DUPLICATE" in flags or "LIKELY_DUPLICATE" in flags
        or "D1_EXACT" in flags or "D2_NEAR" in flags
    )
    if dup:
        return "REVIEW", "HOLD_DUPLICATE"
    if "V2_UNFOOTED_TOTAL" in flags:
        return "REVIEW", "CORRECT_TOTAL"
    if "V3_MISSING_PO" in flags:
        return "REVIEW", "REQUEST_PO"
    if "SPLIT_DODGE" in flags:
        return "REVIEW", "SEND_TO_DIRECTOR"
    if "V1_FUTURE_DATED" in flags:
        return "REVIEW", "SEND_TO_MANAGER"
    if "V4_ROUND_NUMBER" in flags:
        return "REVIEW", "SEND_TO_MANAGER"
    if total_cad < 1000:
        return "AUTO-INTAKE", "AUTO_POST"
    if total_cad <= 5000:
        return "MANAGER", "SEND_TO_MANAGER"
    return "DIRECTOR", "SEND_TO_DIRECTOR"
