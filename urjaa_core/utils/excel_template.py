"""
Generates the unified bulk-upload Excel template for products.

Sheet layout:
  1. products  – one row per product (human-readable names; slug auto-generated)
  2. variants  – one row per variant linked by product_name
  3. instructions – field reference with descriptions and allowed values
"""

import io
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


_GOLD = "C9A14A"
_DARK_BG = "111111"
_ROW_BG = "1A1A1A"
_HEADER_FILL = PatternFill("solid", fgColor=_GOLD)
_ROW_FILL = PatternFill("solid", fgColor=_ROW_BG)
_HEADER_FONT = Font(bold=True, color=_DARK_BG, size=10)
_EXAMPLE_FONT = Font(italic=True, color="888888", size=9)
_LABEL_FONT = Font(bold=True, color=_GOLD, size=10)
_BODY_FONT = Font(color="CCCCCC", size=9)
_REQUIRED_FONT = Font(bold=True, color="FF6B6B", size=9)
_THIN = Side(style="thin", color="333333")
_BORDER = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)


def _header_cell(cell, value: str):
    cell.value = value
    cell.fill = _HEADER_FILL
    cell.font = _HEADER_FONT
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=False)
    cell.border = _BORDER


def _example_cell(cell, value: str):
    cell.value = value
    cell.font = _EXAMPLE_FONT
    cell.fill = _ROW_FILL
    cell.alignment = Alignment(vertical="center", wrap_text=False)
    cell.border = _BORDER


def _set_col_widths(ws, widths: list[int]):
    for col_idx, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width


# ---------------------------------------------------------------------------
# Unified column definitions
# ---------------------------------------------------------------------------

# Products sheet — one row per unique product
# (*) = required; everything else is optional
PRODUCT_COLUMNS = [
    # (column_name, is_required, example_value, description)
    ("product_name",    True,  "Gold Filigree Necklace",         "Unique display name; slug is auto-generated"),
    ("category_name",   True,  "Necklaces",                       "Exact category name as shown in your catalog (case-insensitive)"),
    ("subcategory_name",False, "Choker Necklaces",                "Subcategory name under the given category (optional)"),
    ("description",     False, "Handcrafted 22K gold necklace.",  "Short plain-text description"),
    ("status",          False, "active",                          "active | draft | archived  (default: draft)"),
    ("featured",        False, "false",                           "true | false  (default: false)"),
    ("customizable",    False, "false",                           "true | false  (default: false)"),
]

# Variants sheet — one or more rows per product (linked by product_name)
VARIANT_COLUMNS = [
    ("product_name",       True,  "Gold Filigree Necklace",  "Must exactly match a product_name in the Products sheet"),
    ("variant_sku",        True,  "GFN-22K-16IN",            "Unique SKU code for this variant"),
    ("stock_quantity",     False, "10",                      "Integer >= 0  (default: 0)"),
    ("price_override",     False, "5500",                    "Fixed price in INR; overrides metal-rate computation if set"),
    ("metal_weight_grams", False, "8.5",                     "Decimal grams of metal (used in computed price)"),
    ("making_charges",     False, "1500",                    "Fixed making charge in INR"),
    ("stone_cost",         False, "500",                     "Fixed stone cost in INR"),
    ("base_metal_id",      False, "1",                       "Numeric ID of base metal from your catalog"),
]


def _build_products_sheet(wb: openpyxl.Workbook):
    ws = wb.create_sheet("products")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 20

    # Row 1: column headers
    for col_idx, (col_name, required, _, _desc) in enumerate(PRODUCT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx)
        _header_cell(cell, f"{'* ' if required else ''}{col_name}")

    # Row 2: example values
    for col_idx, (_col_name, _req, example, _desc) in enumerate(PRODUCT_COLUMNS, start=1):
        cell = ws.cell(row=2, column=col_idx)
        _example_cell(cell, example)

    _set_col_widths(ws, [30, 26, 26, 44, 10, 10, 14])
    return ws


def _build_variants_sheet(wb: openpyxl.Workbook):
    ws = wb.create_sheet("variants")
    ws.sheet_view.showGridLines = False
    ws.freeze_panes = "A3"
    ws.row_dimensions[1].height = 22
    ws.row_dimensions[2].height = 20

    for col_idx, (col_name, required, _, _desc) in enumerate(VARIANT_COLUMNS, start=1):
        cell = ws.cell(row=1, column=col_idx)
        _header_cell(cell, f"{'* ' if required else ''}{col_name}")

    for col_idx, (_col_name, _req, example, _desc) in enumerate(VARIANT_COLUMNS, start=1):
        cell = ws.cell(row=2, column=col_idx)
        _example_cell(cell, example)

    _set_col_widths(ws, [30, 18, 14, 16, 20, 18, 14, 16])
    return ws


def _build_instructions_sheet(wb: openpyxl.Workbook):
    ws = wb.create_sheet("instructions")
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 20
    ws.column_dimensions["C"].width = 55
    ws.column_dimensions["D"].width = 32

    def _title(row, text):
        cell = ws.cell(row=row, column=1, value=text)
        cell.font = Font(bold=True, color=_GOLD, size=12)
        cell.alignment = Alignment(vertical="center")
        ws.row_dimensions[row].height = 26

    def _section(row, text):
        cell = ws.cell(row=row, column=1, value=text)
        cell.font = Font(bold=True, color="FFFFFF", size=10)
        cell.fill = PatternFill("solid", fgColor="222222")
        cell.alignment = Alignment(vertical="center")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=4)
        ws.row_dimensions[row].height = 22

    def _field_row(row, col_name, required, example, desc):
        ws.cell(row=row, column=1, value=col_name).font = Font(
            bold=required, color="FFCCAA" if required else "CCCCCC", size=9
        )
        ws.cell(row=row, column=2, value="REQUIRED" if required else "optional").font = Font(
            color="FF6B6B" if required else "666666", size=8, italic=not required
        )
        ws.cell(row=row, column=3, value=desc).font = _BODY_FONT
        ws.cell(row=row, column=3).alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=row, column=4, value=f"e.g.  {example}" if example else "").font = _EXAMPLE_FONT
        ws.row_dimensions[row].height = 18

    r = 1
    _title(r, "BULK UPLOAD — FIELD REFERENCE")
    r += 1
    ws.cell(row=r, column=1, value="* = required column   |   All other columns are optional").font = Font(
        color="888888", size=9, italic=True
    )
    r += 2

    # General rules
    _section(r, "HOW TO USE THIS TEMPLATE")
    r += 1
    rules = [
        "Fill the 'products' sheet — one row per unique product.",
        "Fill the 'variants' sheet — one or more rows per product, linked by product_name.",
        "Export the 'products' sheet as CSV before uploading (File → Save As → CSV).",
        "category_name must match a name in your catalog exactly (case-insensitive). No slug needed.",
        "subcategory_name is optional. If given, it must belong to the specified category.",
        "Product slug is auto-generated from product_name — never provide a slug column.",
        "variant_sku must be globally unique across all stores.",
        "Rows with the same product_name create variants of the same product.",
        "Use price_override to set a fixed price; leave blank to compute via metal rate.",
    ]
    for rule in rules:
        ws.cell(row=r, column=1, value=f"  {rule}").font = Font(color="AAAAAA", size=9)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=4)
        ws.row_dimensions[r].height = 16
        r += 1

    r += 1
    _section(r, "PRODUCTS SHEET FIELDS")
    r += 1
    for col_name, required, example, desc in PRODUCT_COLUMNS:
        _field_row(r, col_name, required, example, desc)
        r += 1

    r += 1
    _section(r, "VARIANTS SHEET FIELDS")
    r += 1
    for col_name, required, example, desc in VARIANT_COLUMNS:
        _field_row(r, col_name, required, example, desc)
        r += 1

    r += 1
    _section(r, "STATUS VALUES")
    r += 1
    for val, desc in [
        ("draft", "Default — product is not visible on the storefront"),
        ("active", "Product is live and visible to customers"),
        ("archived", "Soft-deleted — hidden from all views"),
    ]:
        ws.cell(row=r, column=1, value=val).font = Font(color="C9A14A", bold=True, size=9)
        ws.cell(row=r, column=2, value=desc).font = _BODY_FONT
        ws.merge_cells(start_row=r, start_column=2, end_row=r, end_column=4)
        ws.row_dimensions[r].height = 16
        r += 1


def generate_product_template() -> bytes:
    """Return the unified product bulk-upload Excel template as raw bytes."""
    wb = openpyxl.Workbook()
    default_sheet = wb.active
    wb.remove(default_sheet)

    _build_products_sheet(wb)
    _build_variants_sheet(wb)
    _build_instructions_sheet(wb)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()
