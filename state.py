from __future__ import annotations

from typing import Any, Optional, TypedDict


class BudgetAgentState(TypedDict, total=False):
    # Inputs
    actual_file: str
    uploaded_reference_file: Optional[str]
    reference_file: str
    gold_standard_file: str
    output_dir: str

    # Metadata
    entity: str
    actual_period: str
    reference_period: str
    month_columns: list[str]

    # Data
    actual_df: Any
    budget_parent_df: Any
    budget_detail_df: Any
    normalized_df: Any
    budget_vs_actual_df: Any
    mapping_exceptions_df: Any
    reconciliation_df: Any
    dashboard_data: dict[str, Any]

    # Controls
    source_row_count: int
    source_totals: dict[str, float]
    source_grand_totals: dict[str, float]
    normalized_row_count: int
    reconciliation_status: str
    qa_summary: dict[str, Any]

    # Output / errors
    output_file: str
    validation_error: Optional[str]
