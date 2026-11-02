#!/usr/bin/env python3
"""Seed the fictional Portside Supply Co. bill-intake feed (InTray, Day 6).

Deterministic: random.Random(20261102). Re-running reproduces byte-identical JSON
(fixed seed, sorted keys, no set iteration, sorted sampling pool).

Real-data basis: line-item (Description, Quantity, UnitPrice) tuples are sampled
from the UCI Online Retail corpus at data/raw/Online Retail.xlsx (see
scripts/measure_corpus.py; measured lines/invoice P50=11 / P90=48 sizes the bills,
measured invoice-total P50=$303.84 / P90=$940.89 anchors the total bands).
Everything else (vendors, bills, POs, FX table, noise) is fictional and disclosed
in data/README-data.md.

Money is exact: all amounts are integer cents. Half-cent tax/FX cases (where
banker's vs half-up rounding could disagree across implementations) are detected
and the bill is regenerated, so every printed figure is unambiguous.

Outputs (all under data/):
  outputs/vendor-register.json
  outputs/bills.json            (120 bill arrivals, Oct 26 - Nov 2 2026)
  outputs/posted-register.json  (14 already-posted bills incl. all D1/D2 originals)
  outputs/fx-table.json         (seeded FX rates, disclosed)
  golden-set.json               (30 bills with ground-truth labels)
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261102
rng = random.Random(SEED)

REPO = Path(__file__).resolve().parent.parent
XLSX = REPO / "data" / "raw" / "Online Retail.xlsx"
OUT = REPO / "data" / "outputs"

EDT = timezone(timedelta(hours=-4))  # replay window is EDT per brief (-04:00)
REPLAY = datetime(2026, 11, 2, 8, 41, tzinfo=EDT)
REC_START = datetime(2026, 10, 26, 9, 0, tzinfo=EDT)

FX = {"USD": 1.41, "EUR": 1.53, "GBP": 1.79}
SYMBOLS = {"CAD": "$", "USD": "US$", "EUR": "\u20ac", "GBP": "\u00a3"}


class AmbiguousMoney(Exception):
    """Raised when a tax/FX rounding lands on an exact half-cent."""


# ---------------------------------------------------------------- vendors ---
VENDOR_DEFS = [  # (canonical_name, currency, po_required)
    ("Maple Packaging Ltd.", "CAD", True),
    ("Harbour Office Supplies Inc", "CAD", False),
    ("Northline Industrial Tools", "CAD", False),
    ("GTA Paper & Board Corp", "CAD", False),
    ("Lakeshore Janitorial Supply", "CAD", False),
    ("Beaver Lumber Wholesale", "CAD", True),
    ("Etobicoke Electrical Distributors", "CAD", False),
    ("Portlands Fasteners Co.", "CAD", False),
    ("Dufferin Safety Equipment", "CAD", False),
    ("Liberty Village Print Services", "CAD", False),
    ("Scarborough Steel Supply", "CAD", True),
    ("Mississauga Plastics Inc", "CAD", False),
    ("Don Mills Chemical Supply", "CAD", True),
    ("Yorkdale Uniforms Ltd", "CAD", False),
    ("High Park Landscaping Supply", "CAD", False),
    ("King West Coffee Roasters", "CAD", False),
    ("Junction Textile Mills", "CAD", False),
    ("Leslieville Lighting Co", "CAD", False),
    ("Roncesvalles Refrigeration", "CAD", False),
    ("Danforth Deli Provisions", "CAD", False),
    ("St. Lawrence Produce Wholesale", "CAD", False),
    ("Humber HVAC Parts", "CAD", False),
    ("Weston Road Auto Parts", "CAD", False),
    ("Finch Corridor IT Hardware", "CAD", True),
    ("Bayview Stationery Co", "CAD", False),
    ("Eglinton Paint Supply", "CAD", False),
    ("Sheppard Glass & Mirror", "CAD", False),
    ("Warden Hill Logistics Services", "CAD", False),
    ("Kennedy Road Tire Depot", "CAD", False),
    ("Birchmount Bearing Company", "CAD", True),
    ("Markham Machine Works", "CAD", True),
    ("Vaughan Valve & Fitting", "CAD", True),
    ("Richmond Hill Rigging Supply", "CAD", False),
    ("Oakville Oils & Lubricants", "CAD", True),
    ("Burlington Battery Supply", "CAD", False),
    ("Hamilton Heavy Haulage", "CAD", True),
    ("Great Lakes Freight", "USD", False),
    ("Pacific Rim Components", "USD", False),
    ("Rotterdam Maritime Parts", "EUR", False),
    ("Thames Engineering Supplies", "GBP", False),
]

# vendor_id -> display-name variant (token-set Jaccard vs canonical all >= 0.60)
NAME_VARIANTS = {
    "V001": "Maple Packaging Ltd Toronto",      # 3/4  = 0.75
    "V002": "Harbour Office Supply Inc",        # 3/5  = 0.60
    "V003": "Northline Industrial Tools Ltd",   # 3/4  = 0.75
    "V004": "GTA Paper and Board Corp",         # 4/5  = 0.80
    "V005": "Lakeshore Janitorial Supplies",    # 2/3  = 0.667
    "V006": "Beaver Lumber Wholesale Ltd",      # 3/4  = 0.75
}


def build_vendors():
    vendors = []
    for i, (name, cur, po_req) in enumerate(VENDOR_DEFS, start=1):
        vendors.append({
            "vendor_id": f"V{i:03d}",
            "canonical_name": name,
            "po_required": po_req,
            "currency": cur,
        })
    return vendors


# ------------------------------------------------------------- money utils ---
def tax_cents_cad(subtotal_cents: int) -> int:
    """13% HST on integer cents; raises on exact half-cent."""
    n = 13 * subtotal_cents
    r = n % 100
    if r == 50:
        raise AmbiguousMoney("half-cent tax")
    return n // 100 + (1 if r > 50 else 0)


def fx_to_cad_cents(foreign_cents: int, rate: float) -> int:
    """Convert foreign cents to CAD cents; raises on exact half-cent."""
    R = int(round(rate * 100))
    n = foreign_cents * R
    r = n % 100
    if r == 50:
        raise AmbiguousMoney("half-cent fx")
    return n // 100 + (1 if r > 50 else 0)


def fmt_money(cents: int, cur: str) -> str:
    return f"{SYMBOLS[cur]}{cents / 100:,.2f}"


def tax_label(cur: str) -> str:
    return "Tax (HST 13%)" if cur == "CAD" else "Tax (VAT 0%)"


# ------------------------------------------------------------ corpus pool ---
def load_pool():
    import pandas as pd
    df = pd.read_excel(XLSX, engine="openpyxl")
    df = df.dropna(subset=["Description"])
    df = df[(df["Quantity"] > 0) & (df["UnitPrice"] > 0)]
    pool = []
    for desc, qty, price in zip(df["Description"], df["Quantity"], df["UnitPrice"]):
        d = str(desc).strip()
        if not (4 <= len(d) <= 64) or "?" in d:
            continue
        pool.append((d.title(), int(qty), float(price)))
    pool = sorted(set(pool))  # deterministic order
    return rng.sample(pool, 6000)


# -------------------------------------------------------------- bill parts ---
FROM_NAMES = ["Priya Nair", "Tom Becker", "Aisha Khan", "Marc Dubois",
              "Lena Fischer", "James Whitfield", "Sofia Rossi", "Dan Petrov"]
BODIES = [
    "Hi AP team,\n\nPlease find our invoice {inv} attached for payment.\n\nThanks,\n{name}",
    "Hello,\n\nAttached is invoice {inv} dated {date}. Payment terms net 30.\n\nRegards,\n{name}",
    "Hi,\n\nSending over invoice {inv}. Let me know if you need anything else.\n\nBest,\n{name}",
]
SUBJECTS = [
    "Invoice {inv} from {vendor}",
    "{vendor} - invoice for October",
    "Please process: {inv}",
    "Invoice {inv} attached",
]

DATE_FMTS = ["%b %d %Y", "%Y-%m-%d", "%d/%m/%Y"]  # Oct 28 2026 / 2026-10-28 / 28/10/2026


def vendor_email(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "", name.lower())
    return f"billing@{slug}.example"


def inv_display(kind: int, n: int) -> str:
    if kind == 0:
        return f"Invoice # {n}"
    if kind == 1:
        return f"INV-{n}"
    return f"No. {n}"


def build_lines(pool, target_foreign: float, cur: str):
    """Scale sampled real tuples so the bill lands near target_foreign (bill-currency units)."""
    while True:
        k = max(2, min(44, int(rng.gauss(11, 8))))  # measured P50=11 / P90=48 lines
        tuples = rng.sample(pool, k)
        s0 = sum(q * p for _, q, p in tuples)
        if s0 <= 0:
            continue
        f = target_foreign / s0
        lines = []
        for desc, q, p in tuples:
            nq = max(1, int(round(q * f)))
            unit_cents = int(round(p * 100))
            lines.append({"desc": desc, "qty": nq, "unit_cents": unit_cents,
                          "line_cents": nq * unit_cents})
        subtotal = sum(l["line_cents"] for l in lines)
        if subtotal <= 0:
            continue
        try:
            tax = 0 if cur != "CAD" else tax_cents_cad(subtotal)
            if cur != "CAD":
                fx_to_cad_cents(subtotal, FX[cur])  # just to trigger AmbiguousMoney
        except AmbiguousMoney:
            continue
        return lines, subtotal, tax


def build_lines_exact(pool, target_total_cents: int):
    """CAD only: construct lines whose subtotal+13% tax == target_total_cents exactly."""
    assert is_solvable_total(target_total_cents), f"unsolvable {target_total_cents}"
    guess = int(round(target_total_cents / 1.13))
    S = None
    for cand in range(guess - 800, guess + 800):
        try:
            t = tax_cents_cad(cand)
        except AmbiguousMoney:
            continue
        if cand + t == target_total_cents:
            S = cand
            break
    assert S is not None
    tax = tax_cents_cad(S)
    while True:
        tuples = rng.sample(pool, rng.choice([2, 3]))
        lines, s_rest = [], 0
        for desc, q, p in tuples:
            nq = rng.randint(1, 3)
            unit_cents = int(round(p * 100))
            lines.append({"desc": desc, "qty": nq, "unit_cents": unit_cents,
                          "line_cents": nq * unit_cents})
            s_rest += nq * unit_cents
        rem = S - s_rest
        if rem < 100:  # remainder line must be >= $1.00
            continue
        desc = rng.choice(pool)[0]
        lines.append({"desc": desc, "qty": 1, "unit_cents": rem, "line_cents": rem})
        return lines, S, tax


def render_bill_text(display_name, inv_line, date_str, po, cur, lines,
                     subtotal, tax, total_foreign_cents):
    parts = [display_name]
    if inv_line:
        parts.append(inv_line)
    parts.append(f"Date: {date_str}")
    if po:
        parts.append(f"PO: {po}")
    parts.append(f"Currency: {cur}")
    parts.append("")
    for l in lines:
        parts.append(f"{l['qty']} x {l['desc']} @ {fmt_money(l['unit_cents'], cur)}")
    parts.append("")
    parts.append(f"Subtotal: {fmt_money(subtotal, cur)}")
    parts.append(f"{tax_label(cur)}: {fmt_money(tax, cur)}")
    parts.append(f"Total: {fmt_money(total_foreign_cents, cur)}")
    return "\n".join(parts) + "\n"


def target_total_cad():
    r = rng.random()
    if r < 0.55:
        return rng.uniform(200, 1000)     # bulk: AUTO tier (measured P50=$303.84)
    if r < 0.85:
        return rng.uniform(1000, 4000)    # MANAGER tier
    return rng.uniform(5000, 12000)       # DIRECTOR tier


def is_solvable_total(target_cents: int) -> bool:
    """True iff some subtotal S has S + round(13%*S) == target (13% tax skips some cent values)."""
    guess = int(round(target_cents / 1.13))
    for cand in range(guess - 800, guess + 800):
        try:
            t = tax_cents_cad(cand)
        except AmbiguousMoney:
            continue
        if cand + t == target_cents:
            return True
    return False


def nearest_solvable_total(target_cents: int, max_radius: int = 300) -> int:
    """Nearest cent value >= / <= target that is exactly reachable with 13% tax."""
    for d in range(0, max_radius + 1):
        for cand in (target_cents + d, target_cents - d):
            if cand > 0 and is_solvable_total(cand):
                return cand
    raise AssertionError(f"no solvable total near {target_cents}")


def received_at_random():
    span = (REPLAY - REC_START).total_seconds()
    return REC_START + timedelta(seconds=rng.uniform(0, span))


# ------------------------------------------------------------------ main ---
def main():
    vendors = build_vendors()
    by_id = {v["vendor_id"]: v for v in vendors}
    pool = load_pool()

    used_pairs = set()  # (vendor_id, invoice_number) guard
    bills = []
    seq = [0]

    def add_bill(vendor_id, *, flags, display_name=None, inv_kind=None,
                 inv_number=None, invoice_date=None, received_at=None,
                 po="auto", target_cad=None, exact_total_cents=None,
                 header_delta_cents=0, subject=None, body=None):
        v = by_id[vendor_id]
        cur = v["currency"]
        name = display_name or v["canonical_name"]

        if inv_number is None:
            while True:
                n = rng.randint(10000, 99999)
                if (vendor_id, str(n)) not in used_pairs:
                    break
            used_pairs.add((vendor_id, str(n)))
            inv_number = str(n)
            kind = rng.choice([0, 1, 2]) if inv_kind is None else inv_kind
            inv_line = inv_display(kind, n)
        elif inv_number == "MISSING":
            inv_number = None
            inv_line = ""
        else:
            used_pairs.add((vendor_id, inv_number))
            kind = rng.choice([0, 1, 2]) if inv_kind is None else inv_kind
            inv_line = inv_display(kind, int(inv_number))

        if received_at is None:
            received_at = received_at_random()
        if invoice_date is None:
            invoice_date = (received_at - timedelta(days=rng.randint(1, 20))).date()
        date_str = invoice_date.strftime(rng.choice(DATE_FMTS))

        if po == "auto":
            if v["po_required"]:
                po = f"PO-{rng.randint(1000, 9999)}"
            else:
                po = f"PO-{rng.randint(1000, 9999)}" if rng.random() < 0.4 else None
        elif po == "missing":
            po = None

        rate = FX.get(cur, 1.0)
        if exact_total_cents is not None:
            assert cur == "CAD"
            exact_total_cents = nearest_solvable_total(exact_total_cents)
            lines, subtotal, tax = build_lines_exact(pool, exact_total_cents)
            total_foreign = exact_total_cents
            total_cad_cents = exact_total_cents
        else:
            t_cad = target_cad if target_cad is not None else target_total_cad()
            lines, subtotal, tax = build_lines(pool, t_cad / rate, cur)
            total_foreign = subtotal + tax
            total_cad_cents = (total_foreign if cur == "CAD"
                               else fx_to_cad_cents(total_foreign, rate))

        header_total = total_foreign + header_delta_cents
        text = render_bill_text(name, inv_line, date_str, po, cur, lines,
                                subtotal, tax, header_total)

        sender = rng.choice(FROM_NAMES)
        inv_ref = inv_line or "(no invoice number)"
        if subject is None:
            subject = rng.choice(SUBJECTS).format(inv=inv_ref, vendor=name)
        if body is None:
            body = rng.choice(BODIES).format(
                inv=inv_ref, date=invoice_date.isoformat(), name=sender)

        seq[0] += 1
        bill = {
            "bill_id": f"B{seq[0]:03d}",
            "received_at": received_at.isoformat(),
            "from": f"{sender} <{vendor_email(v['canonical_name'])}>",
            "subject": subject,
            "body": body,
            "bill_text": text,
            "seed_flags": sorted(flags),
            # internal ground-truth fields (stripped before writing bills.json)
            "_vendor_id": vendor_id,
            "_invoice_number": inv_number,
            "_invoice_date": invoice_date.isoformat(),
            "_total_cad_cents": total_cad_cents,
            "_true_total_foreign_cents": total_foreign,
        }
        bills.append(bill)
        return bill

    # ---- posted-register originals for the noise bills (posted BEFORE replay)
    posted = []

    def add_posted(vendor_id, invoice_number, invoice_date, total_cad, posted_days_after=2):
        posted_at = (datetime.combine(invoice_date, datetime.min.time(), tzinfo=EDT)
                     + timedelta(days=posted_days_after))
        posted.append({
            "vendor_id": vendor_id,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date.isoformat(),
            "total_cad": round(total_cad, 2),
            "posted_at": posted_at.isoformat(),
        })

    # ---- exact resubmissions: 4 (originals posted Oct 12-20)
    # totals snapped to the nearest cent value exactly reachable with 13% HST
    exact_specs = [
        (vid, inv, dt, nearest_solvable_total(int(round(t * 100))) / 100)
        for vid, inv, dt, t in [
            ("V001", "48291", datetime(2026, 10, 14).date(), 812.44),
            ("V013", "55017", datetime(2026, 10, 16).date(), 2340.10),
            ("V024", "90312", datetime(2026, 10, 12).date(), 415.75),
            ("V031", "77120", datetime(2026, 10, 19).date(), 1875.00),
        ]
    ]
    for vid, inv, dt, total in exact_specs:
        add_posted(vid, inv, dt, total)

    # ---- near-dupe originals: 4 (originals posted Oct 18-24)
    # resubmission totals target +0.4% (within the 1% D2 band), snapped solvable
    near_specs = []
    for vid, inv, dt, t in [
        ("V013", "98770", datetime(2026, 10, 26).date(), 1235.00),
        ("V006", "33041", datetime(2026, 10, 24).date(), 2870.55),
        ("V002", "61882", datetime(2026, 10, 25).date(), 640.20),
        ("V034", "71509", datetime(2026, 10, 23).date(), 4125.80),
    ]:
        add_posted(vid, inv, dt, t)
        new_total = nearest_solvable_total(int(round(t * 100 * 1.004))) / 100
        assert abs(new_total - t) / t <= 0.01, (new_total, t)
        near_specs.append((vid, inv, dt, new_total))

    # ---- 6 filler posted bills
    filler_vendors = ["V005", "V009", "V017", "V022", "V027", "V039"]
    for i, vid in enumerate(filler_vendors):
        n = rng.randint(10000, 99999)
        dt = datetime(2026, 10, 10 + i * 2, tzinfo=EDT).date()
        total = round(rng.uniform(200, 3000), 2)
        add_posted(vid, str(n), dt, total, posted_days_after=3)

    # ================================================================ bills
    # 6 name-variant bills (B001-B006)
    for vid, variant in NAME_VARIANTS.items():
        add_bill(vid, flags=["name_variant"], display_name=variant,
                 target_cad=rng.uniform(300, 1500))

    # 4 exact resubmissions (B007-B010): same vendor + invoice# as posted
    for vid, inv, dt, total in exact_specs:
        received = (datetime.combine(dt, datetime.min.time(), tzinfo=EDT)
                    + timedelta(days=rng.randint(6, 10)))
        add_bill(vid, flags=["exact_resubmission"], inv_number=inv,
                 invoice_date=dt, received_at=received,
                 exact_total_cents=int(round(total * 100)))

    # 4 near-dupes (B011-B014): total within 1%, date within 7d, inv# differs/missing
    for j, (vid, _inv, dt, new_total) in enumerate(near_specs):
        new_date = dt + timedelta(days=3)
        received = (datetime.combine(new_date, datetime.min.time(), tzinfo=EDT)
                    + timedelta(hours=rng.randint(2, 20)))
        kw = {} if j < 3 else {"inv_number": "MISSING"}
        add_bill(vid, flags=["near_duplicate"], invoice_date=new_date,
                 received_at=received,
                 exact_total_cents=int(round(new_total * 100)), **kw)

    # split-invoice cluster (B015-B018): 4 x $4.6k-4.9k, same vendor+PO, 5-day window
    split_dates = [datetime(2026, 10, 27).date(), datetime(2026, 10, 28).date(),
                   datetime(2026, 10, 30).date(), datetime(2026, 11, 1).date()]
    split_totals = [460000, 475000, 482500, 490000]
    for dt, tc in zip(split_dates, split_totals):
        received = datetime.combine(dt, datetime.min.time(), tzinfo=EDT) + timedelta(hours=9)
        add_bill("V031", flags=["split_cluster"], invoice_date=dt,
                 received_at=received, po="PO-5520", exact_total_cents=tc)

    # 3 missing-PO bills from po_required vendors (B019-B021)
    for vid in ["V001", "V013", "V024"]:
        add_bill(vid, flags=["missing_po"], po="missing",
                 target_cad=rng.uniform(400, 2200))

    # 2 unfooted totals (B022-B023): header off by >$0.05 AND >0.5%
    for _ in range(2):
        base_cents = int(round(rng.uniform(700, 1800) * 100))
        true_total = nearest_solvable_total(base_cents)
        delta = max(6, int(round(true_total * 0.007)))  # >$0.05 and >0.5%
        add_bill("V009", flags=["unfooted_total"], exact_total_cents=true_total,
                 header_delta_cents=delta)

    # 1 future-dated bill (B024): invoice Nov 9 2026 > replay Nov 2
    add_bill("V016", flags=["future_dated"],
             invoice_date=datetime(2026, 11, 9).date(),
             received_at=datetime(2026, 11, 1, 10, 30, tzinfo=EDT),
             target_cad=rng.uniform(300, 900))

    # 2 round-number bills >= $1k (B025-B026): $2,000.00 and $3,000.00 CAD
    add_bill("V020", flags=["round_number"], exact_total_cents=200000,
             target_cad=None)
    add_bill("V007", flags=["round_number"], exact_total_cents=300000,
             target_cad=None)

    # 94 clean bills (B027-B120); first four force the foreign vendors (FX path)
    for vid in ["V037", "V038", "V039", "V040"]:
        add_bill(vid, flags=["clean"], target_cad=rng.uniform(400, 3000))
    for _ in range(90):
        vid = rng.choice([v["vendor_id"] for v in vendors])
        add_bill(vid, flags=["clean"])

    assert len(bills) == 120, len(bills)
    assert len(posted) == 14, len(posted)

    # ---------------------------------------------------------- write files
    def dump(path, obj):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")

    dump(OUT / "vendor-register.json", vendors)
    dump(OUT / "fx-table.json",
         {"USD": 1.41, "EUR": 1.53, "GBP": 1.79, "base": "CAD",
          "disclosed": "seeded"})

    public_bills = []
    for b in bills:
        public_bills.append({k: v for k, v in b.items() if not k.startswith("_")})
    dump(OUT / "bills.json", public_bills)
    dump(OUT / "posted-register.json", posted)

    # ------------------------------------------------------------ golden set
    def label(bill):
        flags = set(bill["seed_flags"])
        t = bill["_total_cad_cents"]
        if flags & {"exact_resubmission", "near_duplicate"}:
            return "HOLD_DUPLICATE"
        if "unfooted_total" in flags:
            return "CORRECT_TOTAL"
        if "missing_po" in flags:
            return "REQUEST_PO"
        if "split_cluster" in flags:
            return "SEND_TO_DIRECTOR"
        if "future_dated" in flags:
            return "SEND_TO_MANAGER"
        if t < 100000:
            return "AUTO_POST"
        if t <= 500000:
            return "SEND_TO_MANAGER"
        return "SEND_TO_DIRECTOR"

    golden = []
    clean = [b for b in bills if b["seed_flags"] == ["clean"]]
    picks = []
    picks += [b for b in clean if b["_total_cad_cents"] < 100000][:6]
    picks += [b for b in clean if 100000 <= b["_total_cad_cents"] <= 500000][:3]
    picks += [b for b in clean if b["_total_cad_cents"] > 500000][:1]
    for flag in ["exact_resubmission", "near_duplicate", "split_cluster",
                 "missing_po", "unfooted_total", "future_dated", "round_number"]:
        picks += [b for b in bills if flag in b["seed_flags"]]
    assert len(picks) == 30, f"golden picks = {len(picks)}"
    for b in picks:
        golden.append({
            "bill_id": b["bill_id"],
            "vendor_id": b["_vendor_id"],
            "invoice_number": b["_invoice_number"],
            "invoice_date": b["_invoice_date"],
            "total_cad": round(b["_total_cad_cents"] / 100, 2),
            "expected_action": label(b),
        })
    dump(REPO / "data" / "golden-set.json", golden)

    # ------------------------------------------------------------- self-check
    from collections import Counter
    c = Counter()
    for b in bills:
        for f in b["seed_flags"]:
            c[f] += 1
    print("bill count:", len(bills))
    print("flag counts:", dict(c))
    print("posted count:", len(posted))
    print("golden count:", len(golden))
    print("golden actions:", dict(Counter(g["expected_action"] for g in golden)))
    # every noise bill's ground truth is internally consistent
    for b in bills:
        assert b["_total_cad_cents"] > 0
    print("OK")


if __name__ == "__main__":
    main()
