"""Measure real corpus stats from the UCI Online Retail dataset.

Writes data/outputs/corpus-stats.json. Every number in data/README-data.md
must come from this step.
"""
from pathlib import Path
import json

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
XLSX = REPO / "data" / "raw" / "Online Retail.xlsx"
OUT = REPO / "data" / "outputs" / "corpus-stats.json"


def main() -> None:
    df = pd.read_excel(XLSX, engine="openpyxl")
    rows_raw = len(df)
    df = df.dropna(subset=["Description"])
    df["InvoiceNo"] = df["InvoiceNo"].astype(str).str.strip()
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce")
    df["UnitPrice"] = pd.to_numeric(df["UnitPrice"], errors="coerce")
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"], errors="coerce")

    # (a) duplicate-InvoiceNo scan (include cancelled C-prefixed invoices)
    counts = df["InvoiceNo"].value_counts()
    dupes = counts[counts > 1]
    total_invoices = int(counts.size)          # distinct InvoiceNo values
    duplicate_invoice_numbers = int((counts > 1).sum())
    duplicate_rows = int(dupe_counts := (counts - 1)[counts > 1].sum()) if duplicate_invoice_numbers else 0
    cancelled = df["InvoiceNo"].str.startswith("C")
    cancelled_invoice_numbers = int(cancelled.groupby(df["InvoiceNo"]).max().sum())

    # (b) line-item-count distribution per invoice (rows per InvoiceNo)
    per_inv_rows = counts.sort_values()
    p50_lines = float(per_inv_rows.quantile(0.50))
    p90_lines = float(per_inv_rows.quantile(0.90))

    # (c) invoice totals: sum(Quantity * UnitPrice) per invoice
    line_total = df["Quantity"] * df["UnitPrice"]
    inv_total_all = line_total.groupby(df["InvoiceNo"]).sum()
    non_cancelled = df.loc[~cancelled]
    inv_total_nc = (non_cancelled["Quantity"] * non_cancelled["UnitPrice"]).groupby(
        non_cancelled["InvoiceNo"]).sum()
    inv_total_nc_pos = inv_total_nc[inv_total_nc > 0]

    # (d1) share of invoices with any line Quantity > 12
    max_qty = df.groupby(df["InvoiceNo"])["Quantity"].max()
    share_qty_gt12 = float((max_qty > 12).mean())

    # (d2) median unit price + most common price decile (positive prices only)
    prices = df.loc[df["UnitPrice"] > 0, "UnitPrice"]
    median_unit_price = float(prices.median())
    lo, hi = float(prices.quantile(0.01)), float(prices.quantile(0.99))
    hist, edges = np.histogram(prices, bins=10, range=(lo, hi))
    best = int(hist.argmax())
    most_common_decile = [round(float(edges[best]), 2), round(float(edges[best + 1]), 2)]
    most_common_decile_share = float(hist[best] / hist.sum())

    # (d3) month seasonality: invoices per month, busiest month
    d = df.loc[df["InvoiceDate"].notna()].copy()
    d["month"] = d["InvoiceDate"].dt.strftime("%Y-%m")
    inv_month = d.drop_duplicates(subset=["InvoiceNo"]).groupby("month")["InvoiceNo"].count()
    busiest = str(inv_month.idxmax())
    invoices_per_month = {str(k): int(v) for k, v in inv_month.items()}

    stats = {
        "source": "UCI Online Retail (Dec 2010 - Dec 2011), Chen/Clement/Das, CC BY 4.0",
        "file": "data/raw/Online Retail.xlsx",
        "raw_rows": int(rows_raw),
        "rows_with_description": int(len(df)),
        "total_invoices_distinct_invoiceno": total_invoices,
        "duplicate_invoice_numbers": duplicate_invoice_numbers,
        "duplicate_resubmission_rows_extra": duplicate_rows,
        "duplicate_invoice_number_rate": round(duplicate_invoice_numbers / total_invoices, 4),
        "cancelled_invoice_numbers_c_prefixed": cancelled_invoice_numbers,
        "lines_per_invoice_p50": p50_lines,
        "lines_per_invoice_p90": p90_lines,
        "invoice_total_non_cancelled_p50": round(float(inv_total_nc_pos.quantile(0.50)), 2),
        "invoice_total_non_cancelled_p90": round(float(inv_total_nc_pos.quantile(0.90)), 2),
        "invoice_total_all_invoices_p50": round(float(inv_total_all.quantile(0.50)), 2),
        "invoice_total_all_invoices_p90": round(float(inv_total_all.quantile(0.90)), 2),
        "share_invoices_any_line_qty_gt_12": round(share_qty_gt12, 4),
        "median_unit_price": round(median_unit_price, 2),
        "most_common_unit_price_decile_p1_p99": most_common_decile,
        "most_common_unit_price_decile_share": round(most_common_decile_share, 4),
        "busiest_month": busiest,
        "invoices_per_month": invoices_per_month,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(json.dumps(stats, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
