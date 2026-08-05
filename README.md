# ChatBot-Research

This project now includes a browser-based web interface that does not depend on
Streamlit, plus dual LLM provider support for both document-grounded answers and
normal AI conversation.

## What it does

- Reads local files from `data/`
- Builds a local retrieval index with TF-IDF
- Answers document questions from retrieved passages only
- Supports normal AI chat when the question is not answered by local files
- Can use `Gemini`, `Typhoon`, or `auto` mode for grounded answers and general chat separately

## Main files

```text
D:\ChatBot-Research\
|-- main.py                # FastAPI web app
|-- rag_service.py         # RAG + provider routing (Gemini + Typhoon)
|-- templates\index.html   # Chat UI
|-- static\app.css         # Styles
|-- static\app.js          # Frontend logic
|-- app.py                 # Legacy Streamlit prototype
|-- requirements.txt
|-- .env
`-- data\
```

## Run the web app

```powershell
cd D:\ChatBot-Research
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Then add one or both keys in `.env`:

```text
TYPHOON_API_KEY=sk-...your real key...
GEMINI_API_KEY=AIza...
```

Start the web server on port `5001`:

```powershell
uvicorn main:app --reload --port 5001
```

Open:

```text
http://localhost:5001
```

## Deploy

This app is a dynamic FastAPI service, so it cannot run on GitHub Pages.
Use a Python app host such as Render or Railway instead.

### Render

1. Push this repository to GitHub.
2. In Render, create a new `Web Service` from the repo.
3. Render can read [`render.yaml`](./render.yaml) automatically, or you can set:

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
Health Check Path: /health
```

4. Add environment variables from `.env.example`, especially:

```text
TYPHOON_API_KEY=...
GEMINI_API_KEY=...
GROUNDED_PROVIDER=auto
CONVERSATION_PROVIDER=auto
TYPHOON_MODEL=typhoon-v2.5-30b-a3b-instruct
GEMINI_MODEL=gemini-3.5-flash
TOP_K=5
MIN_RELEVANCE=0.05
```

5. Deploy, then open the generated Render URL.

### Important note about `data/`

The knowledge base is loaded from the local `data/` folder inside the deployed app.
If you change documents later, you need to either:

- commit the updated files to GitHub and redeploy, or
- add persistent storage / an upload flow

## Supported files

- `.txt`
- `.md`
- `.json`
- `.pdf`

## API endpoints

- `GET /` web chat UI
- `POST /api/chat` ask a question
- `POST /api/reload` rebuild the document index
- `GET /api/status` current knowledge-base stats
- `GET /health` basic health check

## Provider behavior

- `grounded_provider` controls who answers when relevant document passages are found.
- `conversation_provider` controls who answers normal AI chat and fallback responses.
- `auto` prefers Gemini first, then Typhoon if Gemini is unavailable.
- If no provider key is available, the app falls back to a local lightweight assistant response.

## Notes

- Source citations use the path relative to `data/`, so duplicate filenames do not collide.
- Retrieval uses both word n-grams and character n-grams for better matching.
- `app.py` is kept only as a legacy Streamlit prototype; the main web app is `main.py`.
