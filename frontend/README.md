# Plugin Analyst UI (React + Vite + TS)

Phase 7 brings a fuller “plugin product” experience: plugin discovery, question packs, dataset management, and polished flows for chat and insights.

## What’s included
- Plugin catalog and detail views (`/plugins`, `/plugins/:id`) with metadata, question packs, and sample CSV links.
- Dataset management (`/datasets`) with per-plugin filtering, activate/open/delete actions, and a global dataset picker modal.
- Chat with a suggested-questions side panel powered by plugin packs, auto-send toggle, and local chat history per plugin/dataset.
- Insights with quick data-window presets, search/filter, JSON export, skeleton loading states, and richer empty states.
- Persistent global state: active plugin + active dataset per plugin, plus saved dataset lists in `localStorage`.
- Static fallbacks: if backend listing endpoints are missing, the UI loads metadata from `public/plugins/*` and sample CSVs from `public/sample_data`.

## Run the app
```bash
cd frontend
npm install
npm run dev
```
Set `VITE_API_BASE_URL` in `.env` if your backend isn’t on `http://localhost:8000`.

## Demo flow (quick)
1) Open `/plugins` and pick a plugin.  
2) Read what the plugin expects, download the sample CSV if needed.  
3) Click “Upload data” → upload or use the sample.  
4) Confirm the dataset is active in the header or Dashboard.  
5) Go to Chat, pick a suggested question (auto-send optional).  
6) Review SQL/ freshness/ confidence in the trust panel.  
7) Navigate to Insights and run a preset window (e.g., “Last 7 vs previous 7”).  
8) Search/filter insights, export JSON.  
9) Use `/datasets` to switch or delete datasets.  
10) Repeat with another plugin to showcase discovery + onboarding.

## Adding a new plugin’s UI metadata
1) Create `public/plugins/<pluginId>/meta.json` with:
   ```json
   {
     "id": "my_plugin",
     "name": "My Plugin",
     "description": "What it does",
     "domains": ["sales", "ops"],
     "required_columns": ["date", "metric"],
     "sample_csv_url": "/sample_data/my_plugin_sample.csv"
   }
   ```
2) Add `public/plugins/<pluginId>/questions.json` as an array of packs:
   ```json
   [
     { "id": "starter", "title": "Starter pack", "questions": ["Question 1", "..."] }
   ]
   ```
3) Append an entry to `public/plugins/index.json` so the catalog can list it.
4) Drop a sample CSV at `public/sample_data/<pluginId>_sample.csv` (used by “Download sample CSV” and “Load sample data”).

## Backend expectations & fallbacks
- Preferred endpoints: `GET /plugins`, `GET /plugins/{plugin}/questions`, `GET /datasets?plugin=...`, `POST /upload/sales`, `POST /chat`, `POST /insights/run`, `GET /insights/latest`.
- If a list endpoint returns 404, the UI automatically falls back to static `public/plugins/*` JSON and saved dataset lists in `localStorage`.

