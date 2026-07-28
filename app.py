"""
ChatBot-Research — a strict RAG (Retrieval-Augmented Generation) chatbot.

It answers questions EXCLUSIVELY from the documents you place in the /data
folder (.txt, .md, .json, .pdf). If the answer is not present in that source
material, it says so instead of guessing — giving you 100% factual grounding
relative to the provided text.

Stack:  Python + Streamlit (UI) + scikit-learn TF-IDF (local retrieval)
        + Typhoon (Thai LLM, OpenAI-compatible API) for grounded generation.

Run:    streamlit run app.py         # serves on http://localhost:5001
        (port is pinned in .streamlit/config.toml)
"""

import os
import glob
import json
import time

import numpy as np
import streamlit as st
from dotenv import load_dotenv
from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from openai import OpenAI, AuthenticationError, APIError

# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #
load_dotenv(override=True)  # read variables from the local .env file (edits win on reload)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")

# Typhoon uses an OpenAI-compatible endpoint.
BASE_URL = os.getenv("TYPHOON_BASE_URL", "https://api.opentyphoon.ai/v1")
MODEL = os.getenv("MODEL", "typhoon-v2.1-12b-instruct")
TOP_K = int(os.getenv("TOP_K", "5"))
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.05"))

SUPPORTED_EXTENSIONS = (".txt", ".md", ".json", ".pdf")

FILE_ICONS = {".txt": "📄", ".md": "📝", ".json": "🗂️", ".pdf": "📕"}

# A few starter questions shown as clickable chips on an empty conversation.
EXAMPLE_QUESTIONS = [
    "แอปนี้ทำงานที่พอร์ตอะไร?",
    "รองรับไฟล์ประเภทใดบ้าง?",
    "ระบบใช้แนวทางอะไรในการตอบคำถาม?",
    "ถ้าไม่พบคำตอบในเอกสารจะเกิดอะไรขึ้น?",
]

# The exact phrase the assistant must use when the documents don't hold an answer.
NO_ANSWER = "ขออภัยครับ ผมไม่พบคำตอบนี้ในเอกสารที่ให้มา (I don't know based on the provided documents.)"

# The strict instruction that forces grounded, non-hallucinated answers.
SYSTEM_PROMPT = f"""You are ChatBot-Research, a careful research assistant.

You must answer the user's question using ONLY the information contained in the
CONTEXT provided in the user's message. Follow these rules without exception:

1. Base every statement strictly on the CONTEXT. Do not use outside knowledge,
   assumptions, or invented details.
2. If the CONTEXT does not contain enough information to answer, reply exactly
   with this sentence and nothing else:
   "{NO_ANSWER}"
   Do not speculate or fabricate an answer.
3. Quote or closely paraphrase the source text. When helpful, cite the source
   filename shown in the CONTEXT (e.g. "According to handbook.txt, ...").
4. Answer in the same language as the user's question (Thai or English).
5. Be concise, clear, and accurate. Never contradict the CONTEXT.
"""

# --- Basic conversational (small-talk) layer -------------------------------- #
# Instant, offline canned replies for very common greetings / thanks / goodbyes.
GREETING_WORDS = ("สวัสดี", "หวัดดี", "ทักทาย", "hello", "hi ", "hey", "yo ")
THANKS_WORDS = ("ขอบคุณ", "ขอบใจ", "ขอบคุน", "thank", "thx")
BYE_WORDS = ("ลาก่อน", "บายๆ", "บาย ", "แล้วเจอกัน", "bye", "goodbye", "see you")

CANNED = {
    "greeting": "สวัสดีครับ 👋 ผมคือ ChatBot-Research ผู้ช่วยตอบคำถามจากเอกสารของคุณ "
                "อยากถามอะไรเกี่ยวกับเอกสารในระบบ ถามได้เลยครับ 😊",
    "thanks": "ยินดีครับ 😊 ถ้ามีคำถามเกี่ยวกับเอกสารเพิ่มเติม บอกได้เสมอนะครับ",
    "bye": "แล้วเจอกันใหม่ครับ 👋 ขอให้เป็นวันที่ดีครับ",
}


def small_talk(text: str) -> str | None:
    """Return an instant canned reply for clear greetings/thanks/goodbyes, else None."""
    t = f" {text.strip().lower()} "
    short = len(text.strip()) <= 30  # only treat brief messages as pure small talk
    if any(w in t for w in BYE_WORDS):
        return CANNED["bye"]
    if any(w in t for w in THANKS_WORDS):
        return CANNED["thanks"]
    if short and any(w in t for w in GREETING_WORDS):
        return CANNED["greeting"]
    return None


# Friendly fallback persona used when nothing relevant was retrieved and the
# message is not a canned greeting — keeps chat natural WITHOUT inventing facts.
def chitchat_system(kb_files: list[str]) -> str:
    kb = ", ".join(kb_files) if kb_files else "(ยังไม่มีเอกสารในระบบ)"
    return (
        "You are ChatBot-Research, a warm and friendly assistant that answers "
        "questions from the user's document library.\n"
        f"Available documents: {kb}.\n\n"
        "No relevant passage was found for the user's latest message. Therefore:\n"
        "- If it is a greeting, small talk, an emotional message, or a question "
        "about who you are / what you can do, reply naturally, warmly and briefly.\n"
        "- If it is a factual question, say politely that you could not find the "
        "answer in the provided documents, and invite the user to ask about the "
        "documents listed above.\n"
        "Never invent facts about the documents' contents. Reply in the user's "
        "language (Thai or English). Keep it concise (1–3 sentences)."
    )


# --------------------------------------------------------------------------- #
#  Document loading + chunking
# --------------------------------------------------------------------------- #
def _read_pdf(path: str) -> str:
    try:
        reader = PdfReader(path)
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read PDF: {exc}]"


def _read_json(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Pretty-print so structured data stays human-readable for retrieval.
        return json.dumps(data, ensure_ascii=False, indent=2)
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read JSON: {exc}]"


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except Exception as exc:  # noqa: BLE001
        return f"[Could not read file: {exc}]"


def load_documents() -> list[dict]:
    """Read every supported file in /data and return {source, text} records."""
    documents: list[dict] = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "**", "*"), recursive=True)):
        if not os.path.isfile(path):
            continue
        ext = os.path.splitext(path)[1].lower()
        if ext not in SUPPORTED_EXTENSIONS:
            continue

        if ext == ".pdf":
            text = _read_pdf(path)
        elif ext == ".json":
            text = _read_json(path)
        else:
            text = _read_text(path)

        text = (text or "").strip()
        if text:
            documents.append(
                {"source": os.path.basename(path), "ext": ext, "text": text}
            )
    return documents


def chunk_text(text: str, source: str, size: int = 1200, overlap: int = 200) -> list[dict]:
    """Split a document into overlapping windows for finer-grained retrieval."""
    chunks: list[dict] = []
    step = max(size - overlap, 1)
    for start in range(0, len(text), step):
        piece = text[start : start + size].strip()
        if piece:
            chunks.append({"source": source, "text": piece})
        if start + size >= len(text):
            break
    return chunks


# --------------------------------------------------------------------------- #
#  Retrieval index (cached; rebuilt only when the /data folder changes)
# --------------------------------------------------------------------------- #
def _data_signature() -> tuple:
    """A fingerprint of the /data folder so the cache invalidates on change."""
    sig = []
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "**", "*"), recursive=True)):
        if os.path.isfile(path) and path.lower().endswith(SUPPORTED_EXTENSIONS):
            sig.append((path, os.path.getmtime(path), os.path.getsize(path)))
    return tuple(sig)


@st.cache_resource(show_spinner=False)
def build_index(_signature: tuple):
    """Build a TF-IDF index over all document chunks. `_signature` keys the cache."""
    documents = load_documents()

    all_chunks: list[dict] = []
    meta: list[dict] = []
    for doc in documents:
        doc_chunks = chunk_text(doc["text"], doc["source"])
        all_chunks.extend(doc_chunks)
        meta.append(
            {"source": doc["source"], "ext": doc["ext"],
             "chars": len(doc["text"]), "chunks": len(doc_chunks)}
        )

    if not all_chunks:
        return {"chunks": [], "vectorizer": None, "matrix": None, "files": []}

    # ngram_range covers Thai/English phrasing for better lexical matching.
    vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    matrix = vectorizer.fit_transform([c["text"] for c in all_chunks])

    return {
        "chunks": all_chunks,
        "vectorizer": vectorizer,
        "matrix": matrix,
        "files": sorted(meta, key=lambda m: m["source"]),
    }


def retrieve(index: dict, query: str, k: int, min_score: float = MIN_RELEVANCE):
    """Return the top-k most relevant chunks (above the relevance floor)."""
    if not index["chunks"] or index["vectorizer"] is None:
        return []

    query_vec = index["vectorizer"].transform([query])
    scores = cosine_similarity(query_vec, index["matrix"])[0]

    ranked = np.argsort(scores)[::-1][:k]
    results = []
    for idx in ranked:
        score = float(scores[idx])
        if score >= min_score:
            chunk = index["chunks"][idx]
            results.append({"source": chunk["source"], "text": chunk["text"], "score": score})
    return results


def build_context(passages: list[dict]) -> str:
    """Format retrieved passages into a labelled CONTEXT block for the model."""
    blocks = []
    for i, p in enumerate(passages, start=1):
        blocks.append(f"[Source {i}: {p['source']}]\n{p['text']}")
    return "\n\n---\n\n".join(blocks)


def render_sources(passages: list[dict]) -> None:
    """A collapsible panel showing exactly which passages grounded the answer."""
    if not passages:
        return
    with st.expander(f"📎 แหล่งอ้างอิง · {len(passages)} ข้อความ", expanded=False):
        for i, p in enumerate(passages, start=1):
            pct = int(round(p["score"] * 100))
            st.markdown(
                f"**{i}. `{p['source']}`** &nbsp;·&nbsp; "
                f'<span class="cbr-score">ความเกี่ยวข้อง {pct}%</span>',
                unsafe_allow_html=True,
            )
            st.progress(min(max(p["score"], 0.0), 1.0))
            snippet = p["text"].strip().replace("\n", " ")
            st.caption(snippet[:400] + ("…" if len(snippet) > 400 else ""))


# --------------------------------------------------------------------------- #
#  Streamlit UI
# --------------------------------------------------------------------------- #
st.set_page_config(
    page_title="ChatBot-Research",
    page_icon="📚",
    layout="centered",
    initial_sidebar_state="expanded",
)

# Pure dark-mode polish: readable sans-serif type, smooth transitions, clean bubbles.
st.markdown(
    """
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Noto+Sans+Thai:wght@400;500;600;700&display=swap');

      html, body, [class*="css"] {
        font-family: 'Inter', 'Noto Sans Thai', 'Segoe UI', Roboto, system-ui, sans-serif;
        letter-spacing: 0.1px;
      }
      .stApp { background-color: #0E1117; }

      /* Gradient app title */
      .cbr-title {
        font-size: 2rem; font-weight: 700; margin-bottom: 0.1rem;
        background: linear-gradient(90deg, #4F9DFF, #79C0FF, #A371F7);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
      }
      .cbr-sub { color: #8B949E; font-size: 0.95rem; margin-bottom: 1.2rem; }

      /* Chat bubbles: rounded, high-contrast, smooth fade-in */
      [data-testid="stChatMessage"] {
        background: #161B22;
        border: 1px solid #21262D;
        border-radius: 14px;
        padding: 0.85rem 1.05rem;
        margin-bottom: 0.6rem;
        line-height: 1.6;
        animation: cbrFade 0.18s ease-in;
      }
      @keyframes cbrFade { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

      [data-testid="stChatInput"] textarea { font-size: 1rem; }
      html { scroll-behavior: smooth; }

      /* Source citation chips */
      .cbr-src {
        display: inline-block; background: #1F6FEB22; color: #79C0FF;
        border: 1px solid #1F6FEB55; border-radius: 999px;
        padding: 1px 10px; margin: 2px 4px 2px 0; font-size: 0.78rem;
      }
      .cbr-score { color: #7EE787; font-size: 0.8rem; }

      /* Compact sidebar connection pill */
      .cbr-pill {
        display: inline-flex; align-items: center; gap: 6px;
        font-size: 0.8rem; color: #8B949E;
        padding: 2px 10px; border-radius: 999px;
        background: #161B22; border: 1px solid #21262D;
      }
      .cbr-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
      .cbr-dot.on  { background: #3FB950; box-shadow: 0 0 6px #3FB95099; }
      .cbr-dot.off { background: #F85149; box-shadow: 0 0 6px #F8514999; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="cbr-title">📚 ChatBot-Research</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="cbr-sub">ตอบคำถามจากเอกสารของคุณเท่านั้น — ไม่มโน ⚡ powered by Typhoon</div>',
    unsafe_allow_html=True,
)

index = build_index(_data_signature())

# ---- Sidebar -------------------------------------------------------------- #
with st.sidebar:
    # --- Compact connection indicator (no model / endpoint noise) ---------- #
    env_key = os.getenv("TYPHOON_API_KEY", "")
    key_is_placeholder = (not env_key) or env_key.startswith("sk-your-real-typhoon")

    if key_is_placeholder:
        st.markdown(
            '<span class="cbr-pill"><span class="cbr-dot off"></span> ยังไม่ได้เชื่อมต่อ</span>',
            unsafe_allow_html=True,
        )
        api_key = st.text_input(
            "Typhoon API Key", type="password", placeholder="sk-...", label_visibility="collapsed"
        )
    else:
        st.markdown(
            '<span class="cbr-pill"><span class="cbr-dot on"></span> เชื่อมต่อแล้ว</span>',
            unsafe_allow_html=True,
        )
        api_key = env_key

    st.divider()

    # --- Knowledge base (richer: metrics + file table) --------------------- #
    st.subheader("📁 ฐานความรู้")
    if index["files"]:
        total_chunks = sum(f["chunks"] for f in index["files"])
        total_chars = sum(f["chars"] for f in index["files"])
        c1, c2, c3 = st.columns(3)
        c1.metric("ไฟล์", len(index["files"]))
        c2.metric("ท่อนข้อมูล", total_chunks)
        c3.metric("อักขระ", f"{total_chars/1000:.0f}K")

        with st.expander("รายการเอกสาร", expanded=True):
            for f in index["files"]:
                icon = FILE_ICONS.get(f["ext"], "📄")
                st.markdown(
                    f"{icon} `{f['source']}`  \n"
                    f"<span style='color:#8B949E;font-size:0.78rem'>"
                    f"{f['chunks']} ท่อน · {f['chars']/1000:.1f}K อักขระ</span>",
                    unsafe_allow_html=True,
                )
    else:
        st.info(f"ยังไม่มีเอกสาร — วางไฟล์ .txt/.md/.json/.pdf ไว้ที่:\n\n`{DATA_DIR}`")

    st.divider()

    # --- Settings ---------------------------------------------------------- #
    with st.expander("⚙️ ตั้งค่า", expanded=False):
        top_k = st.slider("จำนวนบริบทที่ดึง (Top-K)", 1, 10, TOP_K)
        temperature = st.slider("ความสร้างสรรค์ (Temperature)", 0.0, 1.0, 0.2, 0.1)
        st.caption("Temperature ต่ำ = ยึดตามเอกสารมากขึ้น")

    # --- Actions ----------------------------------------------------------- #
    b1, b2 = st.columns(2)
    if b1.button("🔄 โหลดใหม่", use_container_width=True):
        build_index.clear()
        st.rerun()
    if b2.button("🗑️ ล้างแชท", use_container_width=True):
        st.session_state.messages = []
        st.rerun()

    if st.session_state.get("messages"):
        transcript = "\n\n".join(
            f"{'👤 คุณ' if m['role'] == 'user' else '📚 บอท'}: {m['content']}"
            for m in st.session_state.messages
        )
        st.download_button(
            "⬇️ ดาวน์โหลดบทสนทนา", transcript,
            file_name="chat_history.txt", mime="text/plain",
            use_container_width=True,
        )

# ---- Conversation state --------------------------------------------------- #
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"], avatar="🧑‍💻" if msg["role"] == "user" else "📚"):
        st.markdown(msg["content"])
        if msg.get("passages"):
            render_sources(msg["passages"])
        if msg.get("meta"):
            st.caption(msg["meta"])


# --------------------------------------------------------------------------- #
#  Answering
# --------------------------------------------------------------------------- #
def answer_question(prompt: str, top_k: int, temperature: float, api_key: str) -> None:
    """Retrieve, ground, stream a Typhoon answer, and persist it to history."""
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user", avatar="🧑‍💻"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="📚"):
        if not api_key or api_key.startswith("sk-your-real-typhoon"):
            st.error("กรุณาใส่ Typhoon API key ที่ถูกต้อง (ใน .env หรือช่องด้านซ้าย)")
            st.stop()
        if not index["chunks"]:
            st.warning("ยังไม่มีเอกสารในดัชนี — เพิ่มไฟล์ในโฟลเดอร์ /data แล้วกดโหลดใหม่")
            st.stop()

        passages = retrieve(index, prompt, k=top_k)

        # ---- No relevant document: fall back to basic conversation -------- #
        if not passages:
            canned = small_talk(prompt)
            if canned:
                st.markdown(canned)
                st.session_state.messages.append(
                    {"role": "assistant", "content": canned, "passages": [], "meta": ""}
                )
                return

            # Natural, non-hallucinating fallback via Typhoon.
            try:
                client = OpenAI(api_key=api_key, base_url=BASE_URL)
                kb_files = [f["source"] for f in index["files"]]

                def stream_chat():
                    stream = client.chat.completions.create(
                        model=MODEL,
                        max_tokens=512,
                        temperature=0.6,
                        stream=True,
                        messages=[
                            {"role": "system", "content": chitchat_system(kb_files)},
                            {"role": "user", "content": prompt},
                        ],
                    )
                    for chunk in stream:
                        delta = chunk.choices[0].delta.content
                        if delta:
                            yield delta

                answer = st.write_stream(stream_chat())
            except AuthenticationError:
                st.error("Authentication failed — ตรวจสอบ Typhoon API key อีกครั้ง")
                st.stop()
            except APIError:
                # Even if the API fails, stay graceful instead of crashing.
                answer = NO_ANSWER
                st.markdown(answer)

            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "passages": [], "meta": "💬 โหมดสนทนา"}
            )
            return

        context = build_context(passages)
        user_message = (
            f"CONTEXT:\n{context}\n\n"
            f"QUESTION:\n{prompt}\n\n"
            "Answer using only the CONTEXT above, following your system rules."
        )

        start = time.time()
        try:
            client = OpenAI(api_key=api_key, base_url=BASE_URL)

            def stream_answer():
                stream = client.chat.completions.create(
                    model=MODEL,
                    max_tokens=1024,
                    temperature=temperature,
                    stream=True,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content
                    if delta:
                        yield delta

            answer = st.write_stream(stream_answer())
        except AuthenticationError:
            st.error("Authentication failed — ตรวจสอบ Typhoon API key อีกครั้ง")
            st.stop()
        except APIError as exc:
            st.error(f"API error: {exc}")
            st.stop()

        elapsed = time.time() - start
        render_sources(passages)
        meta = f"⏱ ตอบใน {elapsed:.1f} วินาที · อ้างอิง {len({p['source'] for p in passages})} เอกสาร"
        st.caption(meta)

        st.session_state.messages.append(
            {"role": "assistant", "content": answer, "passages": passages, "meta": meta}
        )


# ---- Suggested questions (only on an empty conversation) ------------------- #
clicked_example = None
if not st.session_state.messages:
    st.markdown("##### 💡 ลองถามคำถามเหล่านี้")
    cols = st.columns(2)
    for i, q in enumerate(EXAMPLE_QUESTIONS):
        if cols[i % 2].button(q, key=f"ex{i}", use_container_width=True):
            clicked_example = q

# ---- Chat input ----------------------------------------------------------- #
typed = st.chat_input("ถามเกี่ยวกับเอกสารของคุณ...")
user_prompt = typed or clicked_example

if user_prompt:
    answer_question(user_prompt, top_k, temperature, api_key)
    if clicked_example:  # refresh so the suggestion chips disappear
        st.rerun()
