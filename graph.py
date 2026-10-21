from __future__ import annotations

from datetime import datetime
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from actual_parser import parse_actual_excel
from budget_parser import parse_reference_budget
from config import DEFAULT_REFERENCE_BUDGET, GOLD_STANDARD_TEMPLATE, OUTPUT_DIR
from finance_engine import build_normalized_data, calculate_outputs
from state import BudgetAgentState
from workbook_builder import build_workbook, validate_workbook


def resolve_inputs(state: BudgetAgentState):
    reference = state.get("uploaded_reference_file") or str(DEFAULT_REFERENCE_BUDGET)
    template = state.get("gold_standard_file") or str(GOLD_STANDARD_TEMPLATE)
    output_dir = state.get("output_dir") or str(OUTPUT_DIR)
    return {
        "reference_file": reference,
        "gold_standard_file": template,
        "output_dir": output_dir,
        "validation_error": None,
    }


def ingest_actual(state: BudgetAgentState):
    try:
        r = parse_actual_excel(state["actual_file"])
        return {
            "actual_df": r.dataframe,
            "entity": r.entity,
            "actual_period": r.actual_period,
            "month_columns": r.month_columns,
            "source_row_count": len(r.dataframe),
            "source_totals": r.source_totals,
            "source_grand_totals": r.source_grand_totals,
        }
    except Exception as e:
        return {"validation_error": f"Actual ingestion failed: {e}"}


def ingest_budget(state: BudgetAgentState):
    if state.get("validation_error"):
        return {}
    try:
        r = parse_reference_budget(state["reference_file"])
        return {
            "budget_parent_df": r.parent_df,
            "budget_detail_df": r.detail_df,
            "reference_period": r.reference_period,
        }
    except Exception as e:
        return {"validation_error": f"Reference Budget ingestion failed: {e}"}


def normalize_map_calculate(state: BudgetAgentState):
    if state.get("validation_error"):
        return {}
    try:
        normalized = build_normalized_data(
            state["actual_df"], state["month_columns"], state["budget_parent_df"], state["budget_detail_df"],
            state["actual_period"], state["reference_period"],
        )
        results = calculate_outputs(
            normalized, state["budget_parent_df"], state["budget_detail_df"], state["month_columns"], state["source_totals"]
        )
        return {
            "normalized_df": normalized,
            "normalized_row_count": len(normalized),
            **results,
        }
    except Exception as e:
        return {"validation_error": f"Finance transformation failed: {e}"}


def reconciliation_gate(state: BudgetAgentState):
    if state.get("validation_error"):
        return "stop"
    normalized = state["normalized_df"]
    if len(normalized) != state["source_row_count"]:
        return "stop"
    source_total = float(state["source_totals"]["TOTAL"])
    normalized_total = float(normalized["ACTUAL_TOTAL"].sum())
    if abs(source_total - normalized_total) > 0.01:
        return "stop"
    return "generate"


def generate_output(state: BudgetAgentState):
    try:
        out_dir = Path(state["output_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        entity = (state.get("entity") or "Entity").strip().replace(" ", "_")
        period = (state.get("actual_period") or "Actual").replace("–", "_to_").replace(" ", "-")
        # Keep user-facing download names short and readable. Streamlit uses a temporary
        # output directory per run, so a timestamp is not needed in the filename.
        output = out_dir / f"{entity}_Budget_vs_Actual_{period}.xlsx"
        build_workbook(
            template_path=state["gold_standard_file"],
            output_path=str(output),
            normalized_df=state["normalized_df"],
            budget_vs_actual_df=state["budget_vs_actual_df"],
            mapping_exceptions_df=state["mapping_exceptions_df"],
            reconciliation_df=state["reconciliation_df"],
            dashboard_data=state["dashboard_data"],
            budget_parent_df=state["budget_parent_df"],
            month_columns=state["month_columns"],
            actual_period=state["actual_period"],
            reference_period=state["reference_period"],
            entity=state["entity"],
        )
        return {"output_file": str(output)}
    except Exception as e:
        return {"validation_error": f"Workbook generation failed: {e}"}


def qa_output(state: BudgetAgentState):
    if state.get("validation_error"):
        return {}
    try:
        qa = validate_workbook(
            state["output_file"],
            expected_rows=state["source_row_count"],
            expected_total=float(state["source_totals"]["TOTAL"]),
        )
        return {"qa_summary": qa, "reconciliation_status": "Passed"}
    except Exception as e:
        return {"validation_error": f"Final workbook QA failed: {e}", "reconciliation_status": "Failed"}


def _route_after_ingest(state: BudgetAgentState):
    return "stop" if state.get("validation_error") else "continue"


def _route_after_transform(state: BudgetAgentState):
    if state.get("validation_error"):
        return "stop"
    result = reconciliation_gate(state)
    if result == "stop" and not state.get("validation_error"):
        return "stop"
    return "generate"


builder = StateGraph(BudgetAgentState)
builder.add_node("resolve_inputs", resolve_inputs)
builder.add_node("ingest_actual", ingest_actual)
builder.add_node("ingest_budget", ingest_budget)
builder.add_node("transform", normalize_map_calculate)
builder.add_node("generate", generate_output)
builder.add_node("qa", qa_output)

builder.add_edge(START, "resolve_inputs")
builder.add_edge("resolve_inputs", "ingest_actual")
builder.add_conditional_edges("ingest_actual", _route_after_ingest, {"continue": "ingest_budget", "stop": END})
builder.add_conditional_edges("ingest_budget", _route_after_ingest, {"continue": "transform", "stop": END})
builder.add_conditional_edges("transform", _route_after_transform, {"generate": "generate", "stop": END})
builder.add_conditional_edges("generate", _route_after_ingest, {"continue": "qa", "stop": END})
builder.add_edge("qa", END)

graph = builder.compile()


def run_budget_agent(actual_file: str, reference_file: str | None = None, output_dir: str | None = None):
    initial: BudgetAgentState = {
        "actual_file": actual_file,
        "uploaded_reference_file": reference_file,
    }
    if output_dir:
        initial["output_dir"] = output_dir
    return graph.invoke(initial)
