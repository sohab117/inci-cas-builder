# API surface

Vercel-compatible Python serverless functions wrapping the engine in `src/`.
Each `api/*.py` file is a FastAPI app that Vercel auto-discovers.

## Endpoints

- `POST /api/analyze` — INCI string in, ingredient analysis + base64 .docx out
- `GET /api/health` — liveness check (`{"status": "ok", "version": "0.1.0"}`)

## Local development

```bash
# Vercel CLI (mimics Vercel's runtime, runs both endpoints together)
npm install -g vercel
vercel dev

# Or — single endpoint with hot reload, faster iteration loop
.venv/bin/uvicorn api.analyze:app --reload --port 8000
.venv/bin/uvicorn api.health:app  --reload --port 8001
```

## Smoke test

```bash
curl -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"inci_string": "Water, Phenoxyethanol", "metadata": {"product_name": "Test"}}'
```

The response is JSON with `ingredients`, `summary`, and `document_base64`.
The base64 string decodes to a .docx — frontend code can `atob` and trigger
a download via a Blob URL without contacting the server again.

## Deployment

```bash
vercel --prod
```

`requirements.txt` at repo root is what Vercel installs into the function
runtime — keep it in sync with `pyproject.toml`'s runtime deps.
