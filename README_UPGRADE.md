# EON Dashboard Upgrade — merged original repository

This ZIP is based on the **original uploaded repository**, not the simplified starter.

## Changes
- Preserved original Company Browser (including its SEC/contact/trigger dossier tabs), Ask EON chatbot, PDF extraction pipeline, tests and Wingman source.
- Added `data/focus-dataset.json`, the 788-record enriched research overlay.
- Added **Enriched Portfolio (788)** navigation page with searchable ranking, focus scoring, provisional Fit/Readiness lenses, buyer research, and clickable company dossier selection.
- Kept the enriched overlay separate from the original 785-row Wingman interface; existing chatbot and SEC sections still run on the Wingman source. The chatbot has NOT been adapted to include the extra 788 research overlay.

## Start
```bash
python -m pip install -r requirements.txt
streamlit run app.py
```
Streamlit Cloud main file path: `app.py`.

## Important limitations
- This integration does not synchronize records automatically between Wingman CSV / SQLite and the enriched overlay.
- The provided snapshot includes 783 scored and five unscored records. Source dates vary.
- Fit and Readiness are provisional heuristic lenses, not validated conversion probabilities.
- No live SEC or external evidence lookup is performed by the new overlay page.
- The existing chatbot and original dossier functionality are preserved as supplied, not independently validated on the deployment environment.
