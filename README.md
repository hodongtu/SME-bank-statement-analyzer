# SME Bank Statement Analyzer — cash-flow analysis from bank statements

Reads one SME customer's dossier (bank statements, 131/331 subsidiary ledgers, financial-statement and VAT XML filings), classifies every transaction by economic nature and produces the report of BRD sections 2.1 → 2.6 (`docs/BRD_*.jpeg`; the BRD has no section 2.2 or 2.6a).

**Principle (inherited from SME post-check):** every figure, threshold, score and sentence in the report is produced by Python. The language model does one job: classify the transactions the rules could not, within a closed vocabulary of 21 categories.

```
read dossier → parse statements / ledgers / tax XML → reference queries (T24, Fraud, CIC, VIRAC, customs, BL/WL, registry)
  → resolve counterparties → classify (bank code → internal-transfer pairing → known party → keyword → model)
  → compute 2.1/2.3/2.4/2.5 → Facts → grade 2.1 + score 2.6 → report MD/PDF/JSON
```

## Running

```bash
pip install -r requirements.txt
python3 samples/make_samples.py              # synthetic cases case_demo, case_missing_data
python3 samples/dummy_db/make_dummy_db.py    # SQLite simulating the reference sources
python3 testing/run_checks.py                # 14 checks, no model calls, no network
```

To analyse a case, open `local_bankstatementanalyzer.ipynb` and set `TESTCASE_ID` and `TAX_CODE`. Outputs go to `logs/<case>_<timestamp>/`: `report.md`, `report.pdf`, `result.json` (for the credit memo to read), `trace.json`, and `classified_transactions.csv` (every transaction with its category, how it was decided and its counterparty, for the credit officer to review).

The model step runs only with `USE_MODEL = True` in the notebook and `MODEL_CLASSIFIER` set in `.env`.

## Language

Everything in the project is English — code, comments, configuration, prompts, logs, checks, this README — except:

- text printed in the report and the transaction CSV, which is read by Vietnamese credit officers (including the BRD's category labels, verbatim);
- keywords matched against Vietnamese source documents (accent-stripped narrative keywords, header synonyms, filename keywords, official e-tax XML tags);
- proper names and sample data.

## Input dossier

`samples/<case>/<upload box>/<file>`. A file's type is decided by its name first, its content second (`config/documents.yaml`):

| Type | Read by | Note |
|---|---|---|
| TCB statement (`BS_*.csv`) | fixed column mapping, `config/statement_formats.yaml` | no balance column → opening/closing reconciliation via T24 |
| Other banks' statements (CSV/Excel) | header row found by synonyms | balance column → transaction-level continuity check |
| 131 / 331 ledgers (CSV/Excel) | `src/agents/extraction/ledger_extraction.py` | repairs lines broken on export; must match the total row |
| Financial statements B01a-DNN, VAT return 01/GTGT (XML) | `src/utils/reading/tax_xml.py` | VAT also reads ct23 (purchases) for section 2.4b |

Not read automatically yet (listed as "not read" in the report): PDF/image statements, CIC PDF, business-registration PDF, inventory detail. CIC and registration data currently come from queries.

## Project Structure

The same layout as `2. SME_creditmemo` and `3. SME_postcheck`.

```
.
├── local_bankstatementanalyzer.ipynb          # Entry point — driver notebook
├── config/
│   ├── prompts/                      # Every system prompt, one Markdown file each; {{name}} filled by the code
│   ├── policy.yaml                   # Every threshold, weight, score band and classification keyword
│   ├── documents.yaml                # Document typing: filename and content keywords
│   └── statement_formats.yaml        # Fixed column mappings per bank
├── src/
│   ├── config.py                     # LLM factory + Config
│   ├── prompts.py                    # The only reader of config/prompts/
│   ├── settings.py                   # The only reader of the YAML files under config/
│   ├── types.py                      # Shared types
│   ├── categories.py                 # The 21 transaction categories
│   ├── facts.py                      # Boundary between collection and grading; an absent value carries its reason
│   ├── agents/
│   │   ├── supervisor.py             # LangGraph orchestrator: the steps and their order
│   │   ├── documents/                # discovery, document typing
│   │   ├── extraction/               # statement and 131/331 ledger parsing
│   │   ├── transactions/             # de-duplication, internal-transfer pairing, counterparties,
│   │   │                             #   classification rules, model step for the remainder
│   │   └── calculator/               # pure computation (no I/O, no clock): period, 2.1, 2.3–2.6
│   ├── tools/                        # SQL queries; arguments come only from code, the model cannot call them
│   ├── utils/
│   │   ├── common.py, numbers.py, paths.py
│   │   ├── reading/                  # tables, tax_xml
│   │   └── report/                   # formatting, render, templates, export
│   └── templates/                    # cashflow-report.md — the report skeleton
├── testing/                          # run_checks.py + verify_*.py; each check also runs on a broken input
├── samples/<testcase>/               # One folder per upload box; synthetic cases + dummy_db/
├── logs/                             # Run outputs (gitignored)
├── docs/                             # BRD
├── .env / .env.example
└── README.md
```

## Default assumptions awaiting business confirmation

All of them live in `config/policy.yaml`:

- "Business inflow" = sales receipts + cash deposits; "operating costs" = suppliers + utilities + salaries/insurance/tax.
- A month is full when statements cover ≥ 80% of its days; 12 months are required (T-11…T); tables show T-12…T.
- 2.1: the BRD's bands overlap at 50%; Medium is read as coverage 50–<80%. If a check could not run (no balances, no Fraud result) the conclusion is at best "limited".
- 2.4a: the 3- and 6-month columns are **monthly averages**; trend = last-3-month average vs monthly average, ±10%.
- 2.5b: the BRD table header says "331"; the 131 ledger is used, with cash received / 131 credit movement.
- 2.6: "score 20/0" is read as 20 when computed but in the worst band, 0 when not computable. Indicator 6 uses a simple rule (legal status, BL/WL, customs turnover vs cash flow) that the officer can override.
- Business inflow / financial-statement revenue is computed only when statements cover ≥ 6 full months of the statement year, with revenue spread evenly by month.

## Sample data

- `case_1`: real statement and ledgers (kept out of git). The dummy DB gives it the fake tax code `9999000001` purely to exercise the queries.
- `case_demo` (tax code `9999000002`) and `case_missing_data` (`9999000003`): entirely fictitious, generated by `make_samples.py`.
