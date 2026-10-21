from __future__ import annotations

from copy import copy
from pathlib import Path
from typing import Any

import pandas as pd
from openpyxl import load_workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.cell.cell import MergedCell


NORMALIZED_HEADERS = [
    "Source Row", "MANAGEMENT_CODE", "LIB4", "ACCOUNT_CODE", "DESCRIPTION", "PARTNER_CODE",
    "PO_NUMBER", "JAN-26", "FEB-26", "Jan-Feb Actual Total", "Scope Classification",
    "Proposed Budget Category", "Proposed Budget Account", "Mapping Status", "Mapping Confidence",
    "Mapping Rationale", "Reference Budget Period", "Actual Reporting Period",
]


def _copy_style_row(ws, src_row: int, dst_row: int, max_col: int):
    for col in range(1, max_col + 1):
        src = ws.cell(src_row, col)
        dst = ws.cell(dst_row, col)
        if src.has_style:
            dst._style = copy(src._style)
        if src.number_format:
            dst.number_format = src.number_format
        if src.alignment:
            dst.alignment = copy(src.alignment)
        if src.font:
            dst.font = copy(src.font)
        if src.fill:
            dst.fill = copy(src.fill)
        if src.border:
            dst.border = copy(src.border)


def _clear_values(ws, start_row: int, end_row: int, max_col: int):
    for row in ws.iter_rows(min_row=start_row, max_row=end_row, min_col=1, max_col=max_col):
        for cell in row:
            if isinstance(cell, MergedCell):
                continue
            cell.value = None


def _write_df(ws, df: pd.DataFrame, start_row: int, start_col: int = 1, style_row: int | None = None):
    for r_idx, row in enumerate(df.itertuples(index=False, name=None), start=start_row):
        if style_row and r_idx > ws.max_row:
            _copy_style_row(ws, style_row, r_idx, start_col + len(row) - 1)
        for c_idx, value in enumerate(row, start=start_col):
            if pd.isna(value):
                value = None
            ws.cell(r_idx, c_idx).value = value


def _normalized_for_excel(df: pd.DataFrame, month_columns: list[str]) -> pd.DataFrame:
    # The template is currently Jan/Feb, but this function adapts the header labels dynamically.
    cols = [
        "SOURCE_ROW", "MANAGEMENT_CODE", "LIB4", "ACCOUNT_CODE", "DESCRIPTION", "PARTNER_CODE", "PO_NUMBER",
        *month_columns, "ACTUAL_TOTAL", "SCOPE_CLASSIFICATION", "PROPOSED_BUDGET_CATEGORY",
        "PROPOSED_BUDGET_ACCOUNT", "MAPPING_STATUS", "MAPPING_CONFIDENCE", "MAPPING_RATIONALE",
        "REFERENCE_BUDGET_PERIOD", "ACTUAL_REPORTING_PERIOD",
    ]
    return df[cols].copy()


def build_workbook(
    template_path: str,
    output_path: str,
    normalized_df: pd.DataFrame,
    budget_vs_actual_df: pd.DataFrame,
    mapping_exceptions_df: pd.DataFrame,
    reconciliation_df: pd.DataFrame,
    dashboard_data: dict[str, Any],
    budget_parent_df: pd.DataFrame,
    month_columns: list[str],
    actual_period: str,
    reference_period: str,
    entity: str,
):
    wb = load_workbook(template_path)

    # --- Normalized Data ---
    ws = wb["Normalized Data"]
    ws["A1"] = "Normalized Data – Full Journal Traceability"
    ws["A2"] = f"{len(normalized_df):,} source transactions. Includes mapped, unmapped, and excluded items."
    headers = [
        "Source Row", "MANAGEMENT_CODE", "LIB4", "ACCOUNT_CODE", "DESCRIPTION", "PARTNER_CODE", "PO_NUMBER",
        *month_columns, f"{actual_period} Actual Total", "Scope Classification", "Proposed Budget Category",
        "Proposed Budget Account", "Mapping Status", "Mapping Confidence", "Mapping Rationale",
        "Reference Budget Period", "Actual Reporting Period",
    ]
    for i, h in enumerate(headers, start=1):
        ws.cell(4, i).value = h
    _clear_values(ws, 5, max(ws.max_row, 5 + len(normalized_df) + 10), len(headers))
    _write_df(ws, _normalized_for_excel(normalized_df, month_columns), 5, style_row=5)

    # --- Budget vs Actual ---
    ws = wb["Budget vs Actual"]
    ws["A1"] = "Budget vs Actual – Operating Non-Labour"
    ws["A2"] = f"PoC comparison: {actual_period} Actual vs selected {reference_period} Reference Budget. This is not {reference_period} consumption."
    bva_headers = [
        "Management Code", "Budget Account", "Budget Category", "Original Budget k€", "Reference Budget €",
        f"Actual {actual_period} €", "Remaining Budget €", "Consumption %", "Mapping Status",
    ]
    for i, h in enumerate(bva_headers, 1):
        ws.cell(4, i).value = h
    _clear_values(ws, 5, max(ws.max_row, 5 + len(budget_vs_actual_df) + 10), 9)
    _write_df(ws, budget_vs_actual_df, 5, style_row=5)

    # --- Mapping & Exceptions ---
    ws = wb["Mapping & Exceptions"]
    ws["A2"] = "PoC mappings are provisional and pending Finance validation. Uncertain items remain Unmapped / Review Required."
    _clear_values(ws, 5, max(ws.max_row, 5 + len(mapping_exceptions_df) + 10), 9)
    _write_df(ws, mapping_exceptions_df, 5, style_row=5)

    # --- Source Reconciliation ---
    ws = wb["Source Reconciliation"]
    ws["A2"] = f"Controls preserve the full Actual source and selected {entity} {reference_period} MSC Non Labour Cost budget."
    _clear_values(ws, 5, max(ws.max_row, 80), 6)
    _write_df(ws, reconciliation_df, 5, style_row=5)
    budget_convention_row = 5 + len(reconciliation_df) + 1
    ws.cell(budget_convention_row, 1).value = "Budget convention"
    ws.cell(budget_convention_row, 2).value = "Management Budget € = ABS(Source Budget k€) × 1,000"
    start = budget_convention_row + 2
    parent_headers = ["Management Code", "Source H1 k€", "Source H2 k€", "Annual Source k€", "Annual Ceiling €", "Description"]
    for i, h in enumerate(parent_headers, 1):
        ws.cell(start, i).value = h
    parent_out = budget_parent_df[[
        "MANAGEMENT_CODE", "SOURCE_H1_KEUR", "SOURCE_H2_KEUR", "ANNUAL_SOURCE_KEUR", "REFERENCE_BUDGET_EUR", "DESCRIPTION"
    ]]
    _write_df(ws, parent_out, start + 1, style_row=start + 1 if start + 1 <= ws.max_row else None)

    # --- Dashboard ---
    ws = wb["Dashboard"]
    ws["A1"] = f"Budget vs Actual Dashboard – {entity}"
    ws["A2"] = f"{reference_period} Reference Budget vs {actual_period} Actual | PoC mappings pending Finance validation"
    ws["B5"] = dashboard_data["reference_budget"]
    ws["B6"] = dashboard_data["operating_non_labour"]
    ws["B7"] = dashboard_data["mapped_actual"]
    ws["B8"] = dashboard_data["unmapped_actual"]
    ws["B9"] = dashboard_data["remaining_budget"]
    ws["B10"] = dashboard_data["consumption_pct"]

    mc = dashboard_data["management_code_table"].copy()
    cat = dashboard_data["category_table"].copy()
    _clear_values(ws, 14, max(ws.max_row, 14 + max(len(mc), len(cat)) + 10), 10)
    mc_headers = ["Management Code", "Reference Budget €", "Mapped Actual €", "Unmapped Actual €", "Consumption %"]
    for i, h in enumerate(mc_headers, 1):
        ws.cell(13, i).value = h
    mc_out = mc[["MANAGEMENT_CODE", "REFERENCE_BUDGET_EUR", "MAPPED_ACTUAL_EUR", "UNMAPPED_ACTUAL_EUR", "CONSUMPTION_PCT"]]
    _write_df(ws, mc_out, 14, 1, style_row=14)

    cat_headers = ["Budget Category", "Reference Budget €", "Mapped Actual €", "Consumption %"]
    for i, h in enumerate(cat_headers, 7):
        ws.cell(13, i).value = h
    cat_out = cat[["BUDGET_CATEGORY", "REFERENCE_BUDGET_EUR", "MAPPED_ACTUAL_EUR", "CONSUMPTION_PCT"]]
    _write_df(ws, cat_out, 14, 7, style_row=14)

    ws["A26"] = (
        f"Governance note: This PoC compares {actual_period} Actual with a user-selected {reference_period} reference baseline. "
        "GL-to-budget mappings marked PoC Proposed are provisional. Unmapped items are intentionally preserved for review."
    )

    # Keep existing template charts where possible. If the template has none, create two.
    if len(ws._charts) < 2:
        ws._charts = []
        mc_end = 13 + len(mc_out)
        chart1 = BarChart()
        chart1.type = "col"
        chart1.style = 10
        chart1.title = "Budget vs Actual by Management Code"
        chart1.y_axis.title = "€"
        data = Reference(ws, min_col=2, max_col=3, min_row=13, max_row=mc_end)
        cats = Reference(ws, min_col=1, min_row=14, max_row=mc_end)
        chart1.add_data(data, titles_from_data=True)
        chart1.set_categories(cats)
        chart1.height = 7
        chart1.width = 12
        ws.add_chart(chart1, "A29")

        cat_end = 13 + len(cat_out)
        chart2 = BarChart()
        chart2.type = "col"
        chart2.style = 10
        chart2.title = "Budget vs Actual by Budget Category"
        chart2.y_axis.title = "€"
        data = Reference(ws, min_col=8, max_col=9, min_row=13, max_row=cat_end)
        cats = Reference(ws, min_col=7, min_row=14, max_row=cat_end)
        chart2.add_data(data, titles_from_data=True)
        chart2.set_categories(cats)
        chart2.height = 7
        chart2.width = 12
        ws.add_chart(chart2, "G29")

    # Force Excel to recalculate formulas/charts on open.
    try:
        wb.calculation.fullCalcOnLoad = True
        wb.calculation.forceFullCalc = True
        wb.calculation.calcMode = "auto"
    except Exception:
        pass

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def validate_workbook(output_path: str, expected_rows: int, expected_total: float) -> dict[str, Any]:
    wb = load_workbook(output_path, data_only=False, read_only=False)
    required = ["Dashboard", "Budget vs Actual", "Normalized Data", "Mapping & Exceptions", "Source Reconciliation"]
    missing = [s for s in required if s not in wb.sheetnames]
    if missing:
        raise ValueError(f"Generated workbook is missing sheets: {missing}")

    ws = wb["Normalized Data"]
    # Data starts at row 5; SOURCE_ROW in col A determines populated rows.
    populated = sum(1 for r in range(5, ws.max_row + 1) if ws.cell(r, 1).value not in (None, ""))
    if populated != expected_rows:
        raise ValueError(f"Normalized Data row count mismatch: expected {expected_rows}, generated {populated}.")

    # Total column is after 7 source fields + N month columns. Find it by header text.
    headers = {str(ws.cell(4, c).value): c for c in range(1, ws.max_column + 1) if ws.cell(4, c).value}
    total_col = next((c for h, c in headers.items() if "Actual Total" in h), None)
    if not total_col:
        raise ValueError("Normalized Data Actual Total column not found.")
    written_total = 0.0
    for r in range(5, ws.max_row + 1):
        v = ws.cell(r, total_col).value
        if isinstance(v, (int, float)):
            written_total += float(v)
    if abs(written_total - expected_total) > 0.01:
        raise ValueError(f"Generated Actual total mismatch: expected {expected_total:.2f}, generated {written_total:.2f}.")

    dashboard_charts = len(wb["Dashboard"]._charts)
    if dashboard_charts < 2:
        raise ValueError(f"Dashboard chart check failed: expected at least 2 charts, found {dashboard_charts}.")

    bva_rows = sum(1 for r in range(5, wb["Budget vs Actual"].max_row + 1) if wb["Budget vs Actual"].cell(r, 1).value)
    if bva_rows == 0:
        raise ValueError("Budget vs Actual sheet is empty.")

    wb.close()
    return {
        "normalized_rows": populated,
        "actual_total": round(written_total, 2),
        "dashboard_charts": dashboard_charts,
        "budget_vs_actual_rows": bva_rows,
        "status": "Passed",
    }
