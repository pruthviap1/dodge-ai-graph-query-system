# dodge-ai-graph-query-system

LLM-powered graph-based data modeling and query system that transforms business data (orders, deliveries, invoices, payments) into a connected graph and enables natural language querying with accurate, data-backed insights.

## Architecture (deployment)

- `Render` -> `backend/` (FastAPI)
- `Vercel` -> `frontend/` (React or static HTML/JS)
- `Gemini` -> LLM (via environment variable keys)

## Repo Structure

- `backend/` -> FastAPI API endpoints, graph construction logic, business/query logic, Gemini integration, and schema models
- `frontend/` -> Chat UI + graph display calling the backend
- `data/` -> unprocessed dataset (jsonl parts, etc.)
- `logs/` -> AI session logs (prompts/responses, debug traces)
- `requirements.txt` -> shared dependency list for local dev (backend)

## Quick Start (local)

### Backend
1. Copy `backend/.env.example` to `backend/.env` and set `GEMINI_API_KEY`.
2. Install deps: `pip install -r backend/requirements.txt`
3. Run: `uvicorn backend.app.main:app --reload --port 8000`

### Frontend
This is static HTML/JS. Open `frontend/index.html` or serve the folder with a static server.
