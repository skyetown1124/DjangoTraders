"""
Additional feature C -- the Price Changes tab's Export to Excel, mirrored from
the ALI Cost tab's server-built export (a separate project, export.py there).

Built on the server with openpyxl from the rows the grid shows (same search,
filters and sort), as one workbook with two flat sheets:
  Products      -- one row per product (the grid's parent rows);
  Price History -- one row per price period (the expanded child rows), with
                   the product's values repeated on every row.
Formats follow the Cost export: currency #,##0.00, dates MM-DD-YYYY, percents
stored as fractions shown as 0.00%, Yes/No flags as Y/N, and a blank cell for
any missing value (never a dash or a zero). The file is named
SupplierPriceChanges_Export_MMddyyyy_hhmmtt.xlsx (am/pm lowercase).
"""

import io
from zoneinfo import ZoneInfo

from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# The file name's time is US Eastern, like the Cost export.
EXPORT_TIME_ZONE = "America/New_York"
CURRENCY = "#,##0.00"
PERCENT = "0.00%"
DATE = "mm-dd-yyyy"
HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")


def _yn(value):
    return None if value is None else ("Y" if value else "N")


# (header, getter, kind); kind is text, int, currency, percent, date or yn
_PRODUCT = [
    ("Product Number", lambda r: r["product_id"], "int"),
    ("Product Name", lambda r: r["name"], "text"),
    ("Category", lambda r: r["category"], "text"),
    ("Quantity Per Unit", lambda r: r["quantity_per_unit"], "text"),
]

PRODUCT_COLUMNS = _PRODUCT + [
    ("Status", lambda r: r["status"], "text"),
    ("List Price", lambda r: r["list_price"], "currency"),
    ("Previous Price", lambda r: r["previous_price"], "currency"),
    ("Latest Price Sold", lambda r: r["sold_price"], "currency"),
    ("Price Change Percent", lambda r: r["change"], "percent"),
    ("Price Since", lambda r: r["since"], "date"),
    ("Last Sold", lambda r: r["last_sold"], "date"),
    ("Orders", lambda r: r["orders"] or None, "int"),
    ("Units Sold", lambda r: r["units"] or None, "int"),
    ("Revenue", lambda r: r["revenue"] or None, "currency"),
    ("Off List", lambda r: _yn(r["off_list"]), "yn"),
    ("Lapsed", lambda r: _yn(r["lapsed"]), "yn"),
]

# The period sheet's getters take (product row, period); the shared product
# columns only need the product row.
PERIOD_COLUMNS = [(header, (lambda g: lambda r, p: g(r))(getter), kind) for header, getter, kind in _PRODUCT] + [
    ("Product Status", lambda r, p: r["status"], "text"),
    ("Period", lambda r, p: p["number"], "int"),
    ("Unit Price", lambda r, p: p["price"], "currency"),
    ("Change From Previous Percent", lambda r, p: p["change"], "percent"),
    ("Price Start Date", lambda r, p: p["start"], "date"),
    ("Price End Date", lambda r, p: p["end"], "date"),
    ("Orders", lambda r, p: p["orders"], "int"),
    ("Units", lambda r, p: p["units"], "int"),
    ("Average Discount Percent", lambda r, p: p["avg_discount"], "percent"),
    ("Revenue", lambda r, p: p["revenue"], "currency"),
]

_FORMATS = {"currency": CURRENCY, "percent": PERCENT, "date": DATE}


def _write_sheet(sheet, columns, records):
    sheet.append([header for header, _, _ in columns])
    for cell in sheet[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    for values in records:
        sheet.append(values)
        row = sheet.max_row
        for col, (_, _, kind) in enumerate(columns, 1):
            if kind in _FORMATS and sheet.cell(row, col).value is not None:
                sheet.cell(row, col).number_format = _FORMATS[kind]
    for col, (header, _, kind) in enumerate(columns, 1):
        widest = max([len(header)] + [len(str(sheet.cell(r, col).value or "")) for r in range(2, sheet.max_row + 1)])
        sheet.column_dimensions[get_column_letter(col)].width = min(max(widest + 2, 10), 40)


def build_workbook(supplier, rows):
    """Returns (xlsx bytes, file name) for the given grid rows."""
    workbook = Workbook()
    products = workbook.active
    products.title = "Products"
    _write_sheet(products, PRODUCT_COLUMNS,
                 [[getter(r) for _, getter, _ in PRODUCT_COLUMNS] for r in rows])

    history = workbook.create_sheet("Price History")
    records = []
    for r in rows:
        for number, period in enumerate(r["periods"], 1):
            period = dict(period, number=number)
            records.append([getter(r, period) for _, getter, _ in PERIOD_COLUMNS])
    _write_sheet(history, PERIOD_COLUMNS, records)

    buffer = io.BytesIO()
    workbook.save(buffer)
    stamp = timezone.localtime(timezone.now(), ZoneInfo(EXPORT_TIME_ZONE)).strftime("%m%d%Y_%I%M%p").lower()
    return buffer.getvalue(), f"SupplierPriceChanges_Export_{stamp}.xlsx"
