from __future__ import annotations

import re
from typing import Any

import pandas as pd

from agent import map_ambiguous_patterns
from config import FIXED_MAPPINGS, TELECOM_DESCRIPTION_KEYWORDS, TRAVEL_DESCRIPTION_KEYWORDS


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _scope_bucket(lib4: str, description: str) -> str:
    l = _norm(lib4)
    d = _norm(description)
    if l == "labour costs":
        return "Labour"
    if l in {"general expense", "advertising & promotion"}:
        return "Operating Non-Labour"
    if "depreciation" in l or "amortization" in l:
        return "Depreciation"
    if l in {"", "(blank)"} or "interest" in d or "accrual of interest" in d:
        return "Interest / accrual / blank"
    return "Other excluded / indirect"


def _deterministic_mapping(row: pd.Series, budget_codes: set[str]):
    gl = str(row["ACCOUNT_CODE"]).strip().replace(".0", "")
    desc = _norm(row["DESCRIPTION"])
    mc = str(row["MANAGEMENT_CODE"]).strip().upper()

    if mc not in budget_codes:
        return None, None, "Unmapped / Review Required", "Low", "Management Code not in selected Reference Budget scope"

    if gl in FIXED_MAPPINGS:
        account, category, rationale = FIXED_MAPPINGS[gl]
        return category, account, "PoC Proposed", "Medium", rationale

    # Mixed-purpose GLs: map only when the description clearly proves the business purpose.
    if gl in {"632810", "632910"} and any(k in desc for k in TRAVEL_DESCRIPTION_KEYWORDS):
        return "Travel and living", "417100C", "PoC Proposed", "Medium", "Travel/accommodation description under approved PoC travel mapping"

    if gl == "677150" and any(k in desc for k in TELECOM_DESCRIPTION_KEYWORDS):
        return "Internal telecommunications costs", "417400A", "PoC Proposed", "Medium", "Description clearly identifies telecom/data expense"

    return None, None, "", "", ""


def build_normalized_data(
    actual_df: pd.DataFrame,
    month_columns: list[str],
    budget_parent_df: pd.DataFrame,
    budget_detail_df: pd.DataFrame,
    actual_period: str,
    reference_period: str,
) -> pd.DataFrame:
    df = actual_df.copy()
    df["_SCOPE_BUCKET"] = [
        _scope_bucket(lib4, desc) for lib4, desc in zip(df["LIB4"], df["DESCRIPTION"])
    ]

    # Output fields expected by the gold-standard workbook.
    df["SCOPE_CLASSIFICATION"] = ""
    df["PROPOSED_BUDGET_CATEGORY"] = None
    df["PROPOSED_BUDGET_ACCOUNT"] = None
    df["MAPPING_STATUS"] = ""
    df["MAPPING_CONFIDENCE"] = ""
    df["MAPPING_RATIONALE"] = ""

    budget_codes = set(budget_parent_df["MANAGEMENT_CODE"].astype(str).str.upper())

    for idx, row in df.iterrows():
        bucket = row["_SCOPE_BUCKET"]
        if bucket != "Operating Non-Labour":
            df.at[idx, "SCOPE_CLASSIFICATION"] = "Excluded"
            df.at[idx, "MAPPING_STATUS"] = "Excluded"
            df.at[idx, "MAPPING_CONFIDENCE"] = "High"
            rationale = {
                "Labour": "Labour excluded from Operating Non-Labour comparison",
                "Depreciation": "Depreciation excluded from Operating Non-Labour comparison",
                "Interest / accrual / blank": "Blank category / interest-accrual scope excluded",
                "Other excluded / indirect": "Indirect/Other excluded from Operating Non-Labour comparison",
            }[bucket]
            df.at[idx, "MAPPING_RATIONALE"] = rationale
            continue

        df.at[idx, "SCOPE_CLASSIFICATION"] = "Operating Non-Labour"
        cat, acc, status, confidence, rationale = _deterministic_mapping(row, budget_codes)
        if status:
            df.at[idx, "PROPOSED_BUDGET_CATEGORY"] = cat
            df.at[idx, "PROPOSED_BUDGET_ACCOUNT"] = acc
            df.at[idx, "MAPPING_STATUS"] = status
            df.at[idx, "MAPPING_CONFIDENCE"] = confidence
            df.at[idx, "MAPPING_RATIONALE"] = rationale

    # Ask the LLM only for unresolved Operating Non-Labour patterns.
    unresolved = df[(df["_SCOPE_BUCKET"] == "Operating Non-Labour") & (df["MAPPING_STATUS"] == "")].copy()
    if not unresolved.empty:
        unresolved["CANDIDATE_ID"] = (
            unresolved["MANAGEMENT_CODE"].astype(str)
            + "|" + unresolved["ACCOUNT_CODE"].astype(str)
            + "|" + unresolved["LIB4"].astype(str)
            + "|" + unresolved["DESCRIPTION"].astype(str)
        )
        candidates = unresolved[
            ["CANDIDATE_ID", "MANAGEMENT_CODE", "LIB4", "ACCOUNT_CODE", "DESCRIPTION"]
        ].drop_duplicates()
        decisions = map_ambiguous_patterns(candidates, budget_detail_df)
        for idx, row in unresolved.iterrows():
            cid = row["CANDIDATE_ID"]
            d = decisions.get(cid)
            if d is None:
                continue
            df.at[idx, "PROPOSED_BUDGET_CATEGORY"] = d.proposed_budget_category
            df.at[idx, "PROPOSED_BUDGET_ACCOUNT"] = d.proposed_budget_account
            df.at[idx, "MAPPING_STATUS"] = d.mapping_status
            df.at[idx, "MAPPING_CONFIDENCE"] = d.confidence
            df.at[idx, "MAPPING_RATIONALE"] = d.rationale

    # Any still unresolved stays explicitly unmapped.
    mask = (df["_SCOPE_BUCKET"] == "Operating Non-Labour") & (df["MAPPING_STATUS"] == "")
    df.loc[mask, "MAPPING_STATUS"] = "Unmapped / Review Required"
    df.loc[mask, "MAPPING_CONFIDENCE"] = "Low"
    df.loc[mask, "MAPPING_RATIONALE"] = "No approved PoC mapping rule"

    df["REFERENCE_BUDGET_PERIOD"] = reference_period
    df["ACTUAL_REPORTING_PERIOD"] = actual_period

    ordered = [
        "SOURCE_ROW", "MANAGEMENT_CODE", "LIB4", "ACCOUNT_CODE", "DESCRIPTION",
        "PARTNER_CODE", "PO_NUMBER", *month_columns, "ACTUAL_TOTAL",
        "SCOPE_CLASSIFICATION", "PROPOSED_BUDGET_CATEGORY", "PROPOSED_BUDGET_ACCOUNT",
        "MAPPING_STATUS", "MAPPING_CONFIDENCE", "MAPPING_RATIONALE",
        "REFERENCE_BUDGET_PERIOD", "ACTUAL_REPORTING_PERIOD", "_SCOPE_BUCKET",
    ]
    return df[ordered].copy()


def _budget_vs_actual(normalized: pd.DataFrame, detail: pd.DataFrame) -> pd.DataFrame:
    mapped = normalized[
        (normalized["_SCOPE_BUCKET"] == "Operating Non-Labour")
        & (normalized["MAPPING_STATUS"].str.startswith("PoC Proposed", na=False))
        & normalized["PROPOSED_BUDGET_ACCOUNT"].notna()
    ].copy()
    mapped_by = (
        mapped.groupby(["MANAGEMENT_CODE", "PROPOSED_BUDGET_ACCOUNT"], dropna=False)["ACTUAL_TOTAL"]
        .sum().reset_index()
        .rename(columns={"PROPOSED_BUDGET_ACCOUNT": "BUDGET_ACCOUNT", "ACTUAL_TOTAL": "ACTUAL_EUR"})
    )
    out = detail.merge(mapped_by, on=["MANAGEMENT_CODE", "BUDGET_ACCOUNT"], how="left")
    out["ACTUAL_EUR"] = out["ACTUAL_EUR"].fillna(0.0)
    out["REMAINING_BUDGET_EUR"] = out["REFERENCE_BUDGET_EUR"] - out["ACTUAL_EUR"]
    out["CONSUMPTION_PCT"] = out.apply(
        lambda r: r["ACTUAL_EUR"] / r["REFERENCE_BUDGET_EUR"] if r["REFERENCE_BUDGET_EUR"] else None,
        axis=1,
    )
    out["MAPPING_STATUS"] = out["ACTUAL_EUR"].apply(lambda x: "PoC Proposed" if x != 0 else "No mapped Actual")
    return out[
        ["MANAGEMENT_CODE", "BUDGET_ACCOUNT", "BUDGET_CATEGORY", "ORIGINAL_BUDGET_KEUR",
         "REFERENCE_BUDGET_EUR", "ACTUAL_EUR", "REMAINING_BUDGET_EUR", "CONSUMPTION_PCT", "MAPPING_STATUS"]
    ]


def _mapping_exceptions(normalized: pd.DataFrame) -> pd.DataFrame:
    records = []
    for (gl, lib4), g in normalized.groupby(["ACCOUNT_CODE", "LIB4"], dropna=False):
        descriptions = [x for x in g["DESCRIPTION"].astype(str).drop_duplicates().tolist() if x][:3]
        mcs = sorted(set(g["MANAGEMENT_CODE"].astype(str)))
        cats = [x for x in g["PROPOSED_BUDGET_CATEGORY"].dropna().astype(str).unique()]
        accs = [x for x in g["PROPOSED_BUDGET_ACCOUNT"].dropna().astype(str).unique()]
        statuses = [x for x in g["MAPPING_STATUS"].dropna().astype(str).unique()]
        confidences = [x for x in g["MAPPING_CONFIDENCE"].dropna().astype(str).unique()]
        rationales = [x for x in g["MAPPING_RATIONALE"].dropna().astype(str).unique()]
        records.append({
            "Actual GL / Account": gl,
            "Actual Category": lib4,
            "Representative Description": " | ".join(descriptions),
            "Management Code(s)": ", ".join(mcs),
            "Proposed Budget Category": " / ".join(cats) if cats else "—",
            "Proposed Budget Account": " / ".join(accs) if accs else "—",
            "Mapping Status": " / ".join(statuses),
            "Confidence": " / ".join(confidences),
            "Rationale": " | ".join(rationales),
        })
    return pd.DataFrame(records)


def calculate_outputs(
    normalized: pd.DataFrame,
    parent: pd.DataFrame,
    detail: pd.DataFrame,
    month_columns: list[str],
    source_totals: dict[str, float],
) -> dict[str, Any]:
    budget_vs_actual = _budget_vs_actual(normalized, detail)
    mapping_exceptions = _mapping_exceptions(normalized)

    bucket = normalized["_SCOPE_BUCKET"]
    labour = float(normalized.loc[bucket == "Labour", "ACTUAL_TOTAL"].sum())
    operating = float(normalized.loc[bucket == "Operating Non-Labour", "ACTUAL_TOTAL"].sum())
    depreciation = float(normalized.loc[bucket == "Depreciation", "ACTUAL_TOTAL"].sum())
    interest = float(normalized.loc[bucket == "Interest / accrual / blank", "ACTUAL_TOTAL"].sum())
    other = float(normalized.loc[bucket == "Other excluded / indirect", "ACTUAL_TOTAL"].sum())
    mapped = float(normalized.loc[normalized["MAPPING_STATUS"].str.startswith("PoC Proposed", na=False), "ACTUAL_TOTAL"].sum())
    unmapped = float(normalized.loc[normalized["MAPPING_STATUS"] == "Unmapped / Review Required", "ACTUAL_TOTAL"].sum())
    excluded = labour + depreciation + interest + other

    parent_total = float(parent["REFERENCE_BUDGET_EUR"].sum())
    parent_signed = float(parent["ANNUAL_SOURCE_KEUR"].sum())
    detail_total = float(detail["REFERENCE_BUDGET_EUR"].sum())
    actual_total = float(normalized["ACTUAL_TOTAL"].sum())

    controls = []
    for c in month_columns:
        controls.append((f"{c} Actual source total", float(source_totals[c]), "€", "Reconciled"))
    controls += [
        ("Actual source total", actual_total, "€", "Reconciled"),
        ("Labour subtotal", labour, "€", "Excluded from operating comparison"),
        ("Operating Non-Labour scope", operating, "€", "Selected comparison population"),
        ("PoC Proposed mapped Actual", mapped, "€", "Pending Finance validation"),
        ("Unmapped / Review Required Actual", unmapped, "€", "Requires review"),
        ("Depreciation subtotal", depreciation, "€", "Excluded"),
        ("Interest/accrual/blank subtotal", interest, "€", "Excluded"),
        ("Other excluded/indirect subtotal", other, "€", "Excluded"),
        ("Excluded total", excluded, "€", "Traceability only"),
        ("Selected Reference Budget (parent totals)", parent_total, "€", "Management ceiling"),
        ("Original signed Reference Budget", parent_signed, "k€", "Source convention"),
        ("Budget detail sum", detail_total, "€", "Detail control"),
        ("Budget detail vs parent difference", detail_total - parent_total, "€", "Hierarchy control"),
        ("Actual control difference", actual_total - sum([labour, operating, depreciation, interest, other]), "€", "Should be 0"),
        ("Operating scope split difference", operating - mapped - unmapped, "€", "Should be 0"),
    ]
    reconciliation = pd.DataFrame(controls, columns=["Control", "Amount", "Unit / Basis", "Status"])

    mc_mapped = normalized[normalized["MAPPING_STATUS"].str.startswith("PoC Proposed", na=False)].groupby("MANAGEMENT_CODE")["ACTUAL_TOTAL"].sum()
    mc_unmapped = normalized[normalized["MAPPING_STATUS"] == "Unmapped / Review Required"].groupby("MANAGEMENT_CODE")["ACTUAL_TOTAL"].sum()
    mc_table = parent[["MANAGEMENT_CODE", "REFERENCE_BUDGET_EUR"]].copy()
    extra_codes = sorted(set(normalized["MANAGEMENT_CODE"]) - set(mc_table["MANAGEMENT_CODE"]))
    if extra_codes:
        mc_table = pd.concat([mc_table, pd.DataFrame({"MANAGEMENT_CODE": extra_codes, "REFERENCE_BUDGET_EUR": 0.0})], ignore_index=True)
    mc_table["MAPPED_ACTUAL_EUR"] = mc_table["MANAGEMENT_CODE"].map(mc_mapped).fillna(0.0)
    mc_table["UNMAPPED_ACTUAL_EUR"] = mc_table["MANAGEMENT_CODE"].map(mc_unmapped).fillna(0.0)
    mc_table["CONSUMPTION_PCT"] = mc_table.apply(
        lambda r: r["MAPPED_ACTUAL_EUR"] / r["REFERENCE_BUDGET_EUR"] if r["REFERENCE_BUDGET_EUR"] else None, axis=1
    )

    cat_budget = detail.groupby("BUDGET_CATEGORY", as_index=False)["REFERENCE_BUDGET_EUR"].sum()
    cat_mapped = normalized[normalized["MAPPING_STATUS"].str.startswith("PoC Proposed", na=False)].groupby("PROPOSED_BUDGET_CATEGORY")["ACTUAL_TOTAL"].sum()
    cat_budget["MAPPED_ACTUAL_EUR"] = cat_budget["BUDGET_CATEGORY"].map(cat_mapped).fillna(0.0)
    cat_budget["CONSUMPTION_PCT"] = cat_budget.apply(
        lambda r: r["MAPPED_ACTUAL_EUR"] / r["REFERENCE_BUDGET_EUR"] if r["REFERENCE_BUDGET_EUR"] else None, axis=1
    )

    dashboard = {
        "reference_budget": parent_total,
        "operating_non_labour": operating,
        "mapped_actual": mapped,
        "unmapped_actual": unmapped,
        "remaining_budget": parent_total - mapped,
        "consumption_pct": mapped / parent_total if parent_total else None,
        "management_code_table": mc_table,
        "category_table": cat_budget,
    }

    return {
        "budget_vs_actual_df": budget_vs_actual,
        "mapping_exceptions_df": mapping_exceptions,
        "reconciliation_df": reconciliation,
        "dashboard_data": dashboard,
    }
