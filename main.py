from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from rag_service import (
    APIError,
    APP_DIR,
    AuthenticationError,
    KnowledgeBase,
    PROVIDERS,
    Settings,
    answer_question,
    gemini_errors,
    resolve_api_key,
)

logger = logging.getLogger(__name__)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    typhoon_api_key: str | None = None
    gemini_api_key: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=10)
    temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    history: list[dict[str, str]] = Field(default_factory=list)
    grounded_provider: str | None = None
    conversation_provider: str | None = None


app = FastAPI(title="Polaris Web", version="2.0.0")
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
kb = KnowledgeBase()


@app.exception_handler(RateLimitExceeded)
def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "ส่งคำถามถี่เกินไปครับ กรุณารอสักครู่แล้วลองใหม่"},
    )


static_dir = APP_DIR / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def _sidebar_payload() -> dict:
    index = kb.current_index()
    settings: Settings = kb.settings
    files = [
        {
            "source": item.source,
            "ext": item.ext,
            "chars": item.chars,
            "chunks": item.chunks,
        }
        for item in index.files
    ]
    return {
        "files": files,
        "doc_count": len(files),
        "chunk_count": sum(item["chunks"] for item in files),
        "char_count": sum(item["chars"] for item in files),
        "has_typhoon_key": bool(resolve_api_key("typhoon")),
        "has_gemini_key": bool(resolve_api_key("gemini")),
        "default_grounded_provider": settings.default_grounded_provider,
        "default_conversation_provider": settings.default_conversation_provider,
        "typhoon_model": settings.typhoon_model,
        "gemini_model": settings.gemini_model,
        "providers": list(PROVIDERS),
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"request": request},
    )


@app.get("/api/status")
def status() -> dict:
    return _sidebar_payload()


@app.post("/api/chat")
@limiter.limit("10/minute")
def chat(request: Request, payload: ChatRequest) -> dict:
    question = payload.message.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Message is required.")

    typhoon_api_key = resolve_api_key("typhoon", payload.typhoon_api_key)
    gemini_api_key = resolve_api_key("gemini", payload.gemini_api_key)

    try:
        result = answer_question(
            kb,
            question,
            typhoon_api_key=typhoon_api_key,
            gemini_api_key=gemini_api_key,
            top_k=payload.top_k,
            temperature=payload.temperature,
            history=payload.history,
            grounded_provider=payload.grounded_provider,
            conversation_provider=payload.conversation_provider,
        )
    # Error details go to the server log only; users get a plain Thai message,
    # since provider exceptions can carry internal request details.
    except ValueError as exc:
        logger.warning("Rejected chat request: %s", exc)
        raise HTTPException(status_code=400, detail="คำถามนี้ส่งไม่ได้ครับ ลองพิมพ์ใหม่อีกครั้ง") from exc
    except (AuthenticationError, APIError, gemini_errors.APIError) as exc:
        logger.exception("AI provider failure")
        raise HTTPException(status_code=502, detail="เชื่อมต่อ AI ไม่สำเร็จในรอบนี้ ลองส่งคำถามใหม่อีกครั้งครับ") from exc
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected chat failure")
        return {
            "answer": "ขออภัยครับ ระบบมีปัญหาชั่วคราว ลองส่งคำถามใหม่ได้เลย",
            "passages": [],
            "images": [],
            "elapsed": 0.0,
            "mode": "server_error",
            "provider_used": "local",
        }

    return result


@app.get("/health")
def health() -> dict:
    payload = _sidebar_payload()
    return {
        "status": "ok",
        "documents": payload["doc_count"],
        "has_typhoon_key": payload["has_typhoon_key"],
        "has_gemini_key": payload["has_gemini_key"],
    }
