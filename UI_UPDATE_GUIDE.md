# EON dashboard UI refresh

This package uses the original extraction, Company Browser (including the original dossier tabs), and Ask EON chatbot. It adds `dashboard/theme.py` to provide consistent dark-mode styling, better sidebar contrast, KPI cards, tabs, and an upgraded `Portfolio & Dossiers (788)` page with row selection, score bars, and exports. The 788-record `data/focus-dataset.json` is intentionally distinct from the Wingman source used by the original pages.

## GitHub deploy
1. Extract this ZIP locally; its root contains `app.py`, `dashboard/`, `data/`, `src/`, and `requirements.txt`.
2. Upload the **contents** to the repository root, keeping paths intact. Do not upload the ZIP as a single file or nest inside an extra folder.
3. Confirm `dashboard/components.py`, `dashboard/theme.py`, `dashboard/pages/15_enriched_portfolio.py`, and `data/focus-dataset.json` appear in GitHub.
4. Deploy `app.py` from branch `main` via Streamlit Community Cloud.

## Validation
Python compilation passed for `app.py` and all `dashboard` modules; data file has 788 records. Live Cloud deployment and full service integration have not been verified.
