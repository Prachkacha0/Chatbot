from __future__ import annotations

import glob
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from dotenv import load_dotenv
from google import genai
from google.genai import errors as gemini_errors
from openai import APIError, AuthenticationError, OpenAI
from pypdf import PdfReader
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

load_dotenv(override=True)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SUPPORTED_EXTENSIONS = (".txt", ".md", ".json", ".pdf")
PROVIDERS = ("auto", "gemini", "typhoon")

NO_ANSWER = (
    "ขออภัยครับ จากเอกสารที่มีอยู่ตอนนี้ "
    "ผมยังไม่พบข้อมูลมากพอที่จะตอบคำถามนี้ได้อย่างชัดเจน"
)

GROUNDING_SYSTEM_PROMPT = """You are ChatBot-Research, acting as the user's personal secretary
(เลขาส่วนตัว) — proactive, warm, and genuinely helpful, not a document-lookup
tool. You have access to a document library as an extra source of information.

Some document passages that may be relevant to the user's question are
included in the prompt below. Follow these rules:

1. If the retrieved document context directly answers the question, use it as
   your primary source and cite the relevant filename.
2. If the document context is only partially relevant, combine it with your
   own general knowledge to give the most complete, helpful answer.
3. If the document context is not actually relevant to the question, ignore
   it completely and just answer normally from your own general knowledge,
   exactly like a competent personal secretary would. NEVER refuse to answer,
   say you don't have enough information, or stay silent just because the
   documents do not cover the topic — always give the user your best helpful
   answer.
4. Never claim a document says something it does not say, and never present a
   guess as if it were a verified quote from a document.
5. Use recent conversation to understand the user's intent.
6. Keep your tone natural, warm, and human, like a trusted assistant speaking
   to someone they support daily. Do not sound robotic.
7. Answer in the same language as the user.
8. Be concise, clear, and accurate.
"""

CONVERSATION_SYSTEM_TEMPLATE = """You are ChatBot-Research, acting as the user's personal secretary
(เลขาส่วนตัว) — proactive, warm, and genuinely helpful.

You can answer everyday questions conversationally, help plan, organize, and
advise, just like a real personal secretary. You also have access to a
document library loaded by the user.

Loaded files:
{files}

Rules:
1. Talk naturally and helpfully, like a real personal secretary — never
   refuse to answer and never leave the user without a useful response.
2. If the user asks general knowledge, casual, or planning/advice questions,
   answer normally and helpfully from your own knowledge.
3. If the user asks specifically about the uploaded documents, file contents,
   citations, local app configuration, or asks you to verify something from the
   files, and you do not have verified document evidence, say so clearly, then
   still offer your best general guidance and invite the user to ask about the
   loaded files more specifically.
4. Never fabricate quotes or claim a file says something when you have not
   verified it.
5. Keep continuity with the recent conversation when helpful.
6. Answer in the same language as the user.
"""

GREETING_WORDS = ("สวัสดี", "หวัดดี", "hello", "hi", "hey")
THANKS_WORDS = ("ขอบคุณ", "ขอบใจ", "thank", "thanks", "thx")
BYE_WORDS = ("ลาก่อน", "บาย", "goodbye", "bye", "see you")
SOCIAL_PHRASES = (
    "คุณทำอะไรได้บ้าง",
    "what can you do",
    "who are you",
    "คุณคือใคร",
    "เป็นยังไงบ้าง",
    "how are you",
)

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    typhoon_base_url: str = field(default_factory=lambda: os.getenv("TYPHOON_BASE_URL", "https://api.opentyphoon.ai/v1"))
    typhoon_model: str = field(default_factory=lambda: os.getenv("TYPHOON_MODEL", os.getenv("MODEL", "typhoon-v2.5-30b-a3b-instruct")))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    top_k: int = field(default_factory=lambda: _env_int("TOP_K", 5))
    min_relevance: float = field(default_factory=lambda: _env_float("MIN_RELEVANCE", 0.05))
    default_grounded_provider: str = field(default_factory=lambda: os.getenv("GROUNDED_PROVIDER", "gemini").lower())
    default_conversation_provider: str = field(default_factory=lambda: os.getenv("CONVERSATION_PROVIDER", "gemini").lower())


@dataclass
class Passage:
    source: str
    text: str
    score: float


@dataclass
class DocumentRecord:
    source: str
    ext: str
    text: str
    path: str


@dataclass
class IndexedFile:
    source: str
    ext: str
    chars: int
    chunks: int


@dataclass
class RetrievalIndex:
    signature: tuple[Any, ...]
    chunks: list[dict[str, str]]
    word_vectorizer: TfidfVectorizer | None
    char_vectorizer: TfidfVectorizer | None
    matrix: Any
    files: list[IndexedFile]


def _normalize_source(path: Path) -> str:
    return path.relative_to(DATA_DIR).as_posix()


def _read_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read PDF: {exc}]"


def _read_json(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read JSON: {exc}]"


def _read_text(path: Path) -> str:
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read()
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read file: {exc}]"


def load_documents() -> list[DocumentRecord]:
    documents: list[DocumentRecord] = []
    pattern = str(DATA_DIR / "**" / "*")
    for raw_path in sorted(glob.glob(pattern, recursive=True)):
        path = Path(raw_path)
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        if ext == ".pdf":
            text = _read_pdf(path)
        elif ext == ".json":
            text = _read_json(path)
        else:
            text = _read_text(path)

        text = text.strip()
        if not text:
            continue

        documents.append(
            DocumentRecord(
                source=_normalize_source(path),
                ext=ext,
                text=text,
                path=str(path),
            )
        )
    return documents


def chunk_text(text: str, source: str, size: int = 1200, overlap: int = 200) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    step = max(size - overlap, 1)
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append({"source": source, "text": piece})
        if start + size >= len(text):
            break
    return chunks


def data_signature() -> tuple[Any, ...]:
    signature = []
    pattern = str(DATA_DIR / "**" / "*")
    for raw_path in sorted(glob.glob(pattern, recursive=True)):
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            stat = path.stat()
            signature.append((str(path), stat.st_mtime, stat.st_size))
    return tuple(signature)


def build_index(signature: tuple[Any, ...]) -> RetrievalIndex:
    documents = load_documents()
    chunks: list[dict[str, str]] = []
    files: list[IndexedFile] = []
    for document in documents:
        doc_chunks = chunk_text(document.text, document.source)
        chunks.extend(doc_chunks)
        files.append(
            IndexedFile(
                source=document.source,
                ext=document.ext,
                chars=len(document.text),
                chunks=len(doc_chunks),
            )
        )

    if not chunks:
        return RetrievalIndex(
            signature=signature,
            chunks=[],
            word_vectorizer=None,
            char_vectorizer=None,
            matrix=None,
            files=[],
        )

    texts = [chunk["text"] for chunk in chunks]
    word_vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    char_vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5))
    word_matrix = word_vectorizer.fit_transform(texts)
    char_matrix = char_vectorizer.fit_transform(texts)
    matrix = hstack([word_matrix, char_matrix])

    return RetrievalIndex(
        signature=signature,
        chunks=chunks,
        word_vectorizer=word_vectorizer,
        char_vectorizer=char_vectorizer,
        matrix=matrix,
        files=sorted(files, key=lambda item: item.source),
    )


def normalize_history(history: list[dict[str, str]] | None, limit: int = 8) -> list[dict[str, str]]:
    if not history:
        return []

    normalized: list[dict[str, str]] = []
    for item in history:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        normalized.append({"role": role, "content": content[:4000]})
    return normalized[-limit:]


def history_as_text(history: list[dict[str, str]] | None) -> str:
    turns = normalize_history(history)
    if not turns:
        return "(none)"
    lines = []
    for turn in turns:
        speaker = "User" if turn["role"] == "user" else "Assistant"
        lines.append(f"{speaker}: {turn['content']}")
    return "\n".join(lines)


def build_context(passages: list[Passage]) -> str:
    blocks = []
    for index, passage in enumerate(passages, start=1):
        blocks.append(f"[Source {index}: {passage.source}]\n{passage.text}")
    return "\n\n---\n\n".join(blocks)


def local_conversation_fallback(question: str, kb_files: list[str]) -> str:
    lowered = question.strip().lower()
    if any(token in lowered for token in BYE_WORDS):
        return "ได้เลยครับ ไว้คุยกันใหม่ ถ้ามีคำถามเกี่ยวกับเอกสารเพิ่มเติมส่งมาได้เสมอครับ"
    if any(token in lowered for token in THANKS_WORDS):
        return "ยินดีครับ ถ้ามีประเด็นไหนอยากให้ช่วยต่อ ถามมาได้เลย"
    if any(token in lowered for token in GREETING_WORDS):
        return "สวัสดีครับ ผมพร้อมช่วยตอบทั้งคำถามทั่วไป และคำถามจากเอกสารที่คุณโหลดไว้ครับ"
    if any(token in lowered for token in SOCIAL_PHRASES):
        return "ผมคือ ChatBot-Research ครับ ตอบคุยทั่วไปได้ และถ้ามีข้อมูลในไฟล์ที่โหลดไว้ ผมจะดึงจากเอกสารมาตอบให้อย่างชัดเจน"
    if kb_files:
        return (
            "ผมยังหาเนื้อหาที่ยืนยันคำตอบนี้จากเอกสารที่โหลดไว้ไม่เจอครับ "
            "ถ้าต้องการ ลองถามให้เจาะจงขึ้น หรือถามเกี่ยวกับไฟล์ที่อยู่ในระบบได้เลย"
        )
    return "ตอนนี้ยังไม่มีเอกสารถูกโหลดในระบบครับ ถ้าเพิ่มไฟล์แล้ว ผมจะช่วยค้นและตอบจากเนื้อหาให้ได้"


def is_social_message(question: str) -> bool:
    lowered = question.strip().lower()
    if not lowered:
        return False
    signals = GREETING_WORDS + THANKS_WORDS + BYE_WORDS + SOCIAL_PHRASES
    return any(token in lowered for token in signals)


def build_grounded_prompt(question: str, passages: list[Passage], history: list[dict[str, str]] | None) -> str:
    return (
        "RECENT CONVERSATION:\n"
        f"{history_as_text(history)}\n\n"
        "DOCUMENT CONTEXT:\n"
        f"{build_context(passages)}\n\n"
        "USER QUESTION:\n"
        f"{question}\n\n"
        "Use the DOCUMENT CONTEXT as your primary source when it is relevant."
        " If it is not relevant to the question, ignore it and answer from your"
        " own knowledge instead, like a helpful personal secretary would. Use"
        " the RECENT CONVERSATION to interpret what the user means. Never"
        " refuse to answer just because the documents don't cover the topic."
    )


def build_conversation_prompt(question: str, history: list[dict[str, str]] | None) -> str:
    return (
        "RECENT CONVERSATION:\n"
        f"{history_as_text(history)}\n\n"
        "LATEST USER MESSAGE:\n"
        f"{question}"
    )


class KnowledgeBase:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._lock = threading.Lock()
        self._index = build_index(data_signature())

    def refresh(self, force: bool = False) -> RetrievalIndex:
        signature = data_signature()
        with self._lock:
            if force or signature != self._index.signature:
                self._index = build_index(signature)
            return self._index

    def current_index(self) -> RetrievalIndex:
        return self.refresh()

    def retrieve(self, query: str, top_k: int | None = None) -> list[Passage]:
        index = self.current_index()
        if not index.chunks or index.word_vectorizer is None or index.char_vectorizer is None:
            return []

        effective_top_k = max(1, top_k or self.settings.top_k)
        word_query = index.word_vectorizer.transform([query])
        char_query = index.char_vectorizer.transform([query])
        query_vector = hstack([word_query, char_query])
        scores = cosine_similarity(query_vector, index.matrix)[0]
        ranked = np.argsort(scores)[::-1][:effective_top_k]

        passages: list[Passage] = []
        for idx in ranked:
            score = float(scores[idx])
            if score < self.settings.min_relevance:
                continue
            chunk = index.chunks[idx]
            passages.append(
                Passage(
                    source=chunk["source"],
                    text=chunk["text"],
                    score=score,
                )
            )
        return passages


def resolve_api_key(name: str, override: str | None = None) -> str:
    env_name = f"{name.upper()}_API_KEY"
    candidate = (override or os.getenv(env_name, "")).strip()
    if not candidate:
        return ""
    if name == "typhoon" and candidate.startswith("sk-your-real-typhoon"):
        return ""
    if name == "gemini" and candidate.startswith("AIzaSy-your-real-gemini"):
        return ""
    return candidate


def normalize_provider_choice(choice: str | None, default: str) -> str:
    provider = (choice or default or "auto").strip().lower()
    if provider not in PROVIDERS:
        return default if default in PROVIDERS else "auto"
    return provider


def provider_order(choice: str) -> list[str]:
    if choice == "typhoon":
        return ["typhoon", "gemini"]
    # "gemini" and "auto" both prefer Gemini first, then fall back to Typhoon.
    return ["gemini", "typhoon"]


class TyphoonProvider:
    name = "typhoon"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self, api_key: str) -> OpenAI:
        # Bound the call so a slow/hanging Typhoon request fails fast enough
        # for the caller (or the auto-fallback logic) to react instead of
        # hanging until the deployment platform's own gateway times out.
        return OpenAI(api_key=api_key, base_url=self.settings.typhoon_base_url, timeout=45.0)

    def grounded(self, *, api_key: str, prompt: str, temperature: float, history: list[dict[str, str]] | None) -> str:
        client = self._client(api_key)
        messages = [{"role": "system", "content": GROUNDING_SYSTEM_PROMPT}]
        messages.extend(normalize_history(history))
        messages.append({"role": "user", "content": prompt})
        completion = client.chat.completions.create(
            model=self.settings.typhoon_model,
            max_tokens=1024,
            temperature=temperature,
            messages=messages,
        )
        answer = completion.choices[0].message.content or NO_ANSWER
        return answer.strip()

    def conversation(self, *, api_key: str, prompt: str, system_instruction: str, temperature: float, history: list[dict[str, str]] | None) -> str:
        client = self._client(api_key)
        messages = [{"role": "system", "content": system_instruction}]
        messages.extend(normalize_history(history))
        messages.append({"role": "user", "content": prompt})
        completion = client.chat.completions.create(
            model=self.settings.typhoon_model,
            max_tokens=768,
            temperature=temperature,
            messages=messages,
        )
        answer = completion.choices[0].message.content or ""
        return answer.strip()


def _gemini_contents(history: list[dict[str, str]] | None, prompt: str) -> list[dict[str, Any]]:
    contents: list[dict[str, Any]] = []
    for turn in normalize_history(history):
        role = "model" if turn["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": turn["content"]}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    return contents


class GeminiProvider:
    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self, api_key: str) -> genai.Client:
        return genai.Client(api_key=api_key, http_options={"timeout": 45_000})

    def grounded(self, *, api_key: str, prompt: str, temperature: float, history: list[dict[str, str]] | None) -> str:
        client = self._client(api_key)
        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=_gemini_contents(history, prompt),
            config={
                "system_instruction": GROUNDING_SYSTEM_PROMPT,
                "temperature": temperature,
            },
        )
        answer = response.text or NO_ANSWER
        return answer.strip()

    def conversation(self, *, api_key: str, prompt: str, system_instruction: str, temperature: float, history: list[dict[str, str]] | None) -> str:
        client = self._client(api_key)
        response = client.models.generate_content(
            model=self.settings.gemini_model,
            contents=_gemini_contents(history, prompt),
            config={
                "system_instruction": system_instruction,
                "temperature": temperature,
            },
        )
        answer = response.text or ""
        return answer.strip()


def _provider_instance(name: str, settings: Settings) -> TyphoonProvider | GeminiProvider:
    if name == "gemini":
        return GeminiProvider(settings)
    return TyphoonProvider(settings)


def available_provider_candidates(choice: str, typhoon_key: str, gemini_key: str) -> list[tuple[str, str]]:
    keys = {
        "typhoon": typhoon_key,
        "gemini": gemini_key,
    }
    candidates: list[tuple[str, str]] = []
    for provider in provider_order(choice):
        key = keys[provider]
        if key:
            candidates.append((provider, key))
    return candidates


def conversation_system(files: list[str]) -> str:
    file_list = ", ".join(files) if files else "(ไม่มีไฟล์ที่โหลดอยู่)"
    return CONVERSATION_SYSTEM_TEMPLATE.format(files=file_list)


def answer_question(
    kb: KnowledgeBase,
    question: str,
    *,
    typhoon_api_key: str,
    gemini_api_key: str,
    top_k: int | None = None,
    temperature: float = 0.2,
    history: list[dict[str, str]] | None = None,
    grounded_provider: str | None = None,
    conversation_provider: str | None = None,
) -> dict[str, Any]:
    started_at = time.time()
    settings = kb.settings
    chat_history = normalize_history(history)
    grounded_choice = normalize_provider_choice(grounded_provider, settings.default_grounded_provider)
    conversation_choice = normalize_provider_choice(conversation_provider, settings.default_conversation_provider)
    kb_files = [item.source for item in kb.current_index().files]
    social_only = is_social_message(question)
    passages = [] if social_only else kb.retrieve(question, top_k=top_k)

    if passages:
        prompt = build_grounded_prompt(question, passages, chat_history)
        answer = ""
        provider_name = ""
        for candidate_name, candidate_key in available_provider_candidates(
            grounded_choice,
            typhoon_api_key,
            gemini_api_key,
        ):
            provider = _provider_instance(candidate_name, settings)
            try:
                answer = provider.grounded(
                    api_key=candidate_key,
                    prompt=prompt,
                    temperature=temperature,
                    history=chat_history,
                )
                provider_name = candidate_name
                break
            except Exception as exc:  # noqa: BLE001
                # Any provider failure (auth, timeout, bad request, network) falls
                # through to the next candidate in available_provider_candidates.
                logger.warning("Grounded provider %s failed: %s", candidate_name, exc)
                continue

        if not answer:
            if not available_provider_candidates(grounded_choice, typhoon_api_key, gemini_api_key):
                return {
                    "answer": "ผมพบข้อมูลที่น่าจะตอบได้จากเอกสารแล้ว แต่ตอนนี้ยังไม่มี API key สำหรับให้โมเดลสรุปคำตอบครับ",
                    "passages": [
                        {"source": passage.source, "text": passage.text, "score": passage.score}
                        for passage in passages
                    ],
                    "elapsed": round(time.time() - started_at, 3),
                    "mode": "needs_provider",
                    "provider_used": "none",
                }
            return {
                "answer": "ผมพบข้อมูลที่เกี่ยวข้องในเอกสารแล้ว แต่เชื่อมต่อโมเดลไม่สำเร็จในรอบนี้ครับ ลองใหม่อีกครั้งได้เลย",
                "passages": [
                    {"source": passage.source, "text": passage.text, "score": passage.score}
                    for passage in passages
                ],
                "elapsed": round(time.time() - started_at, 3),
                "mode": "provider_error",
                "provider_used": "none",
            }

        return {
            "answer": answer,
            "passages": [
                {"source": passage.source, "text": passage.text, "score": passage.score}
                for passage in passages
            ],
            "elapsed": round(time.time() - started_at, 3),
            "mode": "grounded",
            "provider_used": provider_name,
        }

    conversation_prompt = build_conversation_prompt(question, chat_history)
    for candidate_name, candidate_key in available_provider_candidates(
        conversation_choice,
        typhoon_api_key,
        gemini_api_key,
    ):
        provider = _provider_instance(candidate_name, settings)
        try:
            answer = provider.conversation(
                api_key=candidate_key,
                prompt=conversation_prompt,
                system_instruction=conversation_system(kb_files),
                temperature=max(temperature, 0.45),
                history=chat_history,
            )
            if answer:
                return {
                    "answer": answer,
                    "passages": [],
                    "elapsed": round(time.time() - started_at, 3),
                    "mode": "conversation",
                    "provider_used": candidate_name,
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Conversation provider %s failed: %s", candidate_name, exc)
            continue

    return {
        "answer": local_conversation_fallback(question, kb_files),
        "passages": [],
        "elapsed": round(time.time() - started_at, 3),
        "mode": "assistant_fallback",
        "provider_used": "local",
    }


__all__ = [
    "APIError",
    "APP_DIR",
    "AuthenticationError",
    "DATA_DIR",
    "KnowledgeBase",
    "NO_ANSWER",
    "PROVIDERS",
    "Settings",
    "answer_question",
    "gemini_errors",
    "resolve_api_key",
]
