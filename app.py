from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

from config import DEFAULT_REFERENCE_BUDGET
from graph import run_budget_agent

st.set_page_config(page_title="Budget vs Actual Dashboard Agent", page_icon="📊", layout="wide")

st.title("Budget vs Actual Dashboard Agent")
st.caption("Upload the latest Actual Spending file. The current Reference Budget is reused automatically unless you upload a replacement.")

with st.container(border=True):
    st.subheader("1. Actual Spending")
    actual_upload = st.file_uploader("Upload monthly Actual Spending (.xlsx)", type=["xlsx"], key="actual")

with st.container(border=True):
    st.subheader("2. Reference Budget")
    st.info(f"Default reference: {DEFAULT_REFERENCE_BUDGET.name}")
    reference_upload = st.file_uploader(
        "Optional: upload a new Reference Budget for this run",
        type=["xlsx"],
        key="reference",
    )

run = st.button("Generate Budget vs Actual Dashboard", type="primary", disabled=actual_upload is None)

if run and actual_upload:
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        actual_path = td_path / actual_upload.name
        actual_path.write_bytes(actual_upload.getbuffer())

        reference_path = None
        if reference_upload:
            reference_path = td_path / reference_upload.name
            reference_path.write_bytes(reference_upload.getbuffer())

        status = st.status("Generating dashboard…", expanded=True)
        status.write("Reading the complete Actual journal")
        result = run_budget_agent(
            actual_file=str(actual_path),
            reference_file=str(reference_path) if reference_path else None,
            output_dir=str(td_path / "outputs"),
        )

        if result.get("validation_error"):
            status.update(label="Generation failed", state="error", expanded=True)
            st.error(result["validation_error"])
        else:
            status.write("Reconciliation passed")
            status.write("Workbook generated and QA checked")
            status.update(label="Dashboard ready", state="complete", expanded=False)

            qa = result.get("qa_summary", {})
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Transactions processed", f"{qa.get('normalized_rows', 0):,}")
            c2.metric("Actual total", f"€{qa.get('actual_total', 0):,.2f}")
            c3.metric("Dashboard charts", qa.get("dashboard_charts", 0))
            c4.metric("Reconciliation", result.get("reconciliation_status", "Unknown"))

            output_path = Path(result["output_file"])
            st.download_button(
                "Download Budget vs Actual Dashboard",
                data=output_path.read_bytes(),
                file_name=output_path.name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary",
            )
