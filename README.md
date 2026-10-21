# Budget vs Actual Dashboard Agent

A separate LangGraph/LangSmith agent for the Mauritius Budget vs Actual workflow.

## User experience

1. Upload the latest Actual Spending XLSX.
2. The agent automatically uses `reference/reference_budget.xlsx`.
3. Optionally upload a replacement Reference Budget for the run.
4. Click **Generate Budget vs Actual Dashboard**.
5. Download the validated five-sheet Excel workbook.

## Architecture

`Actual XLSX -> Python ingestion -> deterministic classification/mapping rules -> optional LLM mapping for ambiguous patterns -> deterministic finance calculations -> gold-standard template -> workbook QA -> download`

The LLM never owns row ingestion, totals, reconciliation, or Excel writing.

## Files

- `app.py` – Streamlit UI
- `graph.py` – LangGraph orchestration
- `state.py` – shared graph state
- `agent.py` – optional ambiguous mapping agent
- `actual_parser.py` – dynamic Actual workbook ingestion
- `budget_parser.py` – 2027 IOO Reference Budget parser
- `finance_engine.py` – classification, mapping, reconciliation, aggregation
- `workbook_builder.py` – fills the gold-standard template and performs final QA
- `reference/reference_budget.xlsx` – default Reference Budget
- `reference/gold_standard.xlsx` – target workbook template
- `sample_data/MSC Maurice - Feb26.xlsx` – regression-test Actual file

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## LangSmith

Set the variables in `.env.example`. LangGraph/LangChain calls will then be traceable in the configured LangSmith project.

## Important governance

- All source transactions are retained.
- Labour/Depreciation/Interest/Other exclusions are not counted as Unmapped.
- Only Operating Non-Labour is mapped to the Non-Labour reference budget.
- PoC mappings remain provisional.
- Workbook generation stops if transaction row count or Actual total does not reconcile.
