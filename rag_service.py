from __future__ import annotations

import glob
import json
import logging
import os
import re
import threading
import time
from collections import Counter
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

from web_search import WebSource, search_wikipedia

load_dotenv(override=True)

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SUPPORTED_EXTENSIONS = (".txt", ".md", ".json", ".pdf")
PROVIDERS = ("auto", "gemini", "typhoon")

NO_ANSWER = (
    "ขออภัยครับ จากเอกสารที่มีอยู่ตอนนี้ "
    "ผมยังไม่พบข้อมูลมากพอที่จะตอบคำถามนี้ได้อย่างชัดเจน"
)

CREATOR_ANSWER = (
    "ผู้สร้างของผมคือสภาศักดิ์สิทธิ์แห่งครุศาสตร์คอมพิวเตอร์ มจพ.\n"
    "นายวีรภัทร ครุนิติวัฒน์\n"
    "นายธนพล อวยพร\n"
    "นายปรัชคฌา น้อยศรี\n"
    "นายอภินัทธ์ ลัดลอย\n"
    "นายธีระวัฒน์ นุ่นงาม"
)
# Served only via is_creator_question, never through the LLM prompts: a prompt
# rule made the model also answer this to "ใครคือคนสร้างคอมพิวเตอร์".

GROUNDING_SYSTEM_PROMPT = """You are Polaris, a research assistant that answers questions
about basic computer knowledge strictly from a Thai computer textbook, using
only the provided document context.

Rules:
1. Answer ONLY using information from the DOCUMENT CONTEXT provided. Do not
   use outside knowledge, general knowledge, or make assumptions beyond what
   the documents say.
2. Stay as close to the textbook's own wording as possible: reuse its
   sentences and terms instead of rephrasing them, and keep numbers, dates,
   names and technical terms exactly as written in the context (for example
   keep "John Napier" in English and keep Thai numerals such as ๒๑๕๘ as-is;
   do not transliterate or convert them).
3. Cite where each point comes from using the label after "|" in that
   source's header, in parentheses, e.g. (ตำราหน้า 13). Never cite as
   "Source 1" or by filename.
4. If the document context does not contain enough information to answer the
   question, respond with: "ขออภัยครับ ไม่พบข้อมูลที่เกี่ยวข้องในเอกสาร
   กรุณาถามเกี่ยวกับเนื้อหาในตำราพื้นฐานคอมพิวเตอร์ครับ"
   Give that same response when the context is only loosely related to what
   the user actually wants. Judge the intent together with the recent
   conversation (a short follow-up such as "and for work?" continues the
   previous request). In particular, the textbook does not cover buying
   advice, recommended specs or builds, prices, or current products -- for
   those, give the response above. Never repurpose a textbook passage to
   answer a different question from the one being asked.
5. Never guess, infer, or add information not found in the documents.
6. Use recent conversation to understand the user's intent.
7. Keep your tone natural and clear.
8. Answer in the same language as the user.
9. Default to a short, direct answer: a few sentences or a short list (roughly
   3-5 bullet points) covering only what the question actually asked for.
   Only give a long detailed answer when the user explicitly asks for it.
"""

GENERAL_COMPUTER_SYSTEM_PROMPT = """You are Polaris, a research assistant for a
basic-computer textbook research project. The document knowledge base did NOT contain
an answer to this question, so you are answering from your own general knowledge
instead — but ONLY because the question is about computers, hardware, or
information technology.

Rules:
1. First check what kind of message this is:
   a. Casual small talk aimed at you (e.g. "กินข้าวยัง", "เป็นไงบ้าง",
      "เหนื่อยไหม"): reply warmly in one short sentence and invite a
      computer question, e.g. "ผมเป็น AI เลยไม่ได้กินข้าวครับ
      ถ้ามีคำถามเรื่องคอมพิวเตอร์ ถามได้เลยครับ". Rules 2-7 don't apply.
   b. A request for information that is not about computers, hardware,
      software, or IT (e.g. recipes, travel, weather): respond ONLY with:
      "ขออภัยครับ ผมตอบได้เฉพาะเรื่องคอมพิวเตอร์เท่านั้นครับ"
   c. Otherwise it's a computer question: follow the rules below.
2. If it IS about computers, answer helpfully and accurately from your own
   knowledge.
3. Always start the answer by making clear this is general knowledge, not from
   the textbook: begin with the phrase "เรื่องนี้ไม่มีในตำราครับ แต่ตามความรู้ทั่วไป"
   and continue straight into the answer in the same sentence (do not write
   "..." after it). Never imply the answer came from the textbook.
4. Keep your tone natural and clear.
5. Answer in the same language as the user.
6. Default to a short, direct answer: a few sentences or a short list (roughly
   3-5 bullet points). Only give a long detailed answer when the user
   explicitly asks for it.
7. Your training data has a cutoff and may be years older than today's date
   (given below). If the question depends on recent information -- the
   latest or newest models, current prices, release dates, current market
   leaders, or "this year" -- give the newest information you genuinely
   know (do not understate or hold back newer knowledge you have), and say
   roughly which year it is from (e.g. "ข้อมูลที่ผมมีล่าสุดคือ ...").
   NEVER guess or extrapolate products, versions, or events that would have
   come after your training data just because today's date is later -- do
   not invent model names or numbers. Then say briefly that newer ones may
   exist by today and suggest checking an official source. Timeless concepts
   (what an ALU is, how RAM works) need no such warning.
"""


WEB_RESULTS_RULES = """
WEB SEARCH RESULTS from Wikipedia, retrieved today, are included in the user
message. They are more recent than your training data. When they cover the
question, these rules replace the opening phrase in rule 3 and the warning in
rule 7:
- Base time-sensitive facts (latest or current models, lineups, release dates)
  on the results, not on your memory, and do not add an "information may be
  out of date" warning for facts the results cover.
- Begin with "เรื่องนี้ไม่มีในตำราครับ แต่จากข้อมูลบน Wikipedia" and continue
  straight into the answer in the same sentence.
- Copy model names, numbers and dates exactly as the results state them;
  never change a year or month from what the results say.
- Cite the article you used, e.g. (Wikipedia: iPhone).
- If the results don't actually answer the question, ignore them and follow
  rules 1-7 as written.
"""

SEARCH_QUERY_SYSTEM_PROMPT = """You turn a user's latest message into English
Wikipedia search terms. Wikipedia search matches article titles and topics, so
use the name of the product line, brand, or technology (e.g. iPhone, Nvidia
GeForce, AMD Ryzen, Linux) -- never words like latest, newest, best, fastest,
now, or a year.
Output ONLY one search term, or two separated by " | " when the question
compares or spans two product lines (e.g. Intel Core | AMD Ryzen). No quotes,
no explanation.
Output the single word NONE when the message is small talk or not about
computers, technology, or IT.
Use the recent conversation to resolve follow-ups, e.g. a follow-up
"isn't the newest one 18?" after asking about iPhones becomes: iPhone 18
"""


SEARCH_QUERY_TIME_BUDGET = 8.0


def general_computer_system_prompt(*, with_web_results: bool = False) -> str:
    rules = WEB_RESULTS_RULES if with_web_results else ""
    return f"{GENERAL_COMPUTER_SYSTEM_PROMPT}{rules}\nToday's date: {time.strftime('%Y-%m-%d')}\n"


CONVERSATION_SYSTEM_TEMPLATE = """You are Polaris, acting as the user's personal secretary
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
7. Default to a short, direct answer: a few sentences or a short list (roughly
   3-5 bullet points) covering only what the question actually asked for.
   Only give a long, fully detailed answer when the user explicitly asks for
   full detail, a complete guide, or asks you to elaborate.
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
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    gemini_timeout: float = field(default_factory=lambda: _env_float("GEMINI_TIMEOUT", 12.0))
    web_search: str = field(default_factory=lambda: os.getenv("WEB_SEARCH", "wikipedia").lower())
    embedding_model: str = field(default_factory=lambda: os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"))
    top_k: int = field(default_factory=lambda: _env_int("TOP_K", 5))
    # 0.06, not higher: list-style textbook pages (e.g. ตำราหน้า ๕๑–๕๖) pack many
    # topics per chunk, so even the correct page scores ~0.06-0.10. Loosely
    # related hits are still filtered by the grounded prompt's refusal rule.
    min_relevance: float = field(default_factory=lambda: _env_float("MIN_RELEVANCE", 0.06))
    semantic_weight: float = field(default_factory=lambda: _env_float("SEMANTIC_WEIGHT", 0.0))
    exact_qa_threshold: float = field(default_factory=lambda: _env_float("EXACT_QA_THRESHOLD", 0.85))
    max_images_per_answer: int = field(default_factory=lambda: max(0, _env_int("MAX_IMAGES_PER_ANSWER", 2)))
    default_grounded_provider: str = field(default_factory=lambda: os.getenv("GROUNDED_PROVIDER", "typhoon").lower())
    default_conversation_provider: str = field(default_factory=lambda: os.getenv("CONVERSATION_PROVIDER", "typhoon").lower())


_ARABIC_TO_THAI_DIGITS = str.maketrans("0123456789", "๐๑๒๓๔๕๖๗๘๙")


@dataclass
class Passage:
    source: str
    text: str
    score: float
    page_range: str = ""
    page_label: str = ""

    @property
    def citation(self) -> str:
        if self.page_label:
            # Thai numerals, as printed on the textbook's pages.
            return f"ตำราหน้า {self.page_label.translate(_ARABIC_TO_THAI_DIGITS)}"
        if self.page_range:
            return "ตำราส่วนต้นเล่ม"
        return self.source

    def to_payload(self) -> dict[str, Any]:
        return {"source": self.source, "page": self.citation, "text": self.text, "score": self.score}


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
class QAPair:
    source: str
    question: str
    answer: str


@dataclass
class RetrievalIndex:
    signature: tuple[Any, ...]
    chunks: list[dict[str, str]]
    word_vectorizer: TfidfVectorizer | None
    char_vectorizer: TfidfVectorizer | None
    matrix: Any
    embeddings: np.ndarray | None
    files: list[IndexedFile]
    qa_pairs: list[QAPair]
    qa_vectorizer: TfidfVectorizer | None
    qa_matrix: Any


def _normalize_source(path: Path) -> str:
    return path.relative_to(DATA_DIR).as_posix()


# Some PDF-to-Markdown extractions of legacy Thai fonts (e.g. THSarabunPSK)
# encode certain vowels/tone marks as Private Use Area codepoints instead of
# their standard Thai Unicode equivalents -- the PDF's own embedded
# ToUnicode CMap maps those glyphs to PUA codepoints directly, so no
# extraction step can recover the "correct" codepoint automatically. Mapping
# verified by cross-referencing the PDF's ToUnicode CMap against known words
# (e.g. "หน่วย", "เปิด", "คอมพิวเตอร์") throughout the textbook dataset.
_THAI_PUA_FIX = {
    "": "ิ",  # sara i      (เปิด, ฟิลด์)
    "": "ี",  # sara ii     (ปี)
    "": "ึ",  # sara ue     (ฝึก)
    "": "ื",  # sara uee    (ฟันเฟือง, ปืนใหญ่)
    "": "่",  # mai ek      (ปุ่ม, ฝ่าย)
    "": "้",  # mai tho     (ไฟฟ้า)
    "": "์",  # thanthakhat (ไดรฟ์)
    "": "่",  # mai ek      (หน่วย, ส่วน)
    "": "้",  # mai tho     (หน้า, ข้อมูล)
    "": "๊",  # mai tri     (โต๊ะ, สล๊อต)
    "": "์",  # thanthakhat (คอมพิวเตอร์, อุปกรณ์)
    "": "ั",  # mai han-akat(สถาปัตยกรรม, ปัจจุบัน)
    "": "็",  # mai taikhu  (เป็น)
    "": "่",  # mai ek      (ฝั่ง)
    "": "้",  # mai tho     (ฟลอปปี้ดิสก์)
    "": "ฬ",  # ro rua -> lo (นาฬิกา)
}
_THAI_PUA_PATTERN = re.compile("|".join(re.escape(k) for k in _THAI_PUA_FIX))


def fix_thai_pua_marks(text: str) -> str:
    return _THAI_PUA_PATTERN.sub(lambda m: _THAI_PUA_FIX[m.group(0)], text)


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
            return fix_thai_pua_marks(handle.read())
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


_PDF_PAGE_PRESERVATION_MARKER = 'dataset_type: "pdf-page-preservation"'
_PDF_PAGE_HEADING = re.compile(r"^### หน้า PDF (\d+)\s*$", re.MULTILINE)
_PDF_PAGE_TEXT_BLOCK = re.compile(r"```text\n(.*?)\n```", re.DOTALL)


def is_pdf_page_preservation_dataset(text: str) -> bool:
    """Detect the "PDF page preservation" markdown export format (one
    ### หน้า PDF NNN section per page, page metadata table, then the raw
    PDF text layer in a ```text block) via its frontmatter marker, so this
    dataset can be chunked by page instead of by a fixed character count."""
    return _PDF_PAGE_PRESERVATION_MARKER in text[:500]


def extract_pdf_pages(text: str) -> list[tuple[int, str]]:
    """Split a page-preservation markdown export into (page_number, page_text)
    pairs, keeping only each page's raw PDF text layer -- not the surrounding
    metadata (page size, detected headings, image coordinate tables), which
    would otherwise pollute what the retrieval index searches over."""
    headings = list(_PDF_PAGE_HEADING.finditer(text))
    pages: list[tuple[int, str]] = []
    for index, heading in enumerate(headings):
        page_number = int(heading.group(1))
        section_start = heading.end()
        section_end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        section = text[section_start:section_end]
        text_match = _PDF_PAGE_TEXT_BLOCK.search(section)
        if not text_match:
            continue
        page_text = " ".join(text_match.group(1).split())
        if page_text:
            pages.append((page_number, page_text))
    return pages


_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
_LEADING_PAGE_NUMBER = re.compile(r"([๐-๙0-9]+)\s")


def _printed_page_offset(pages: list[tuple[int, str]]) -> int | None:
    """Most common gap between a page's PDF index and the page number printed
    at the top of it. Pages that don't open with a number (chapter title
    pages, front matter) still follow the same offset."""
    offsets: Counter[int] = Counter()
    for page_number, page_text in pages:
        match = _LEADING_PAGE_NUMBER.match(page_text)
        if match:
            offsets[page_number - int(match.group(1).translate(_THAI_DIGITS))] += 1
    return offsets.most_common(1)[0][0] if offsets else None


def _format_range(numbers: list[int]) -> str:
    return str(numbers[0]) if numbers[0] == numbers[-1] else f"{numbers[0]}-{numbers[-1]}"


def chunk_pdf_pages(
    text: str,
    source: str,
    *,
    min_chars: int = 600,
    max_pages: int = 3,
) -> list[dict[str, str]]:
    """Chunk a page-preservation dataset by page instead of by a fixed
    character offset, so each chunk stays aligned with real page boundaries
    (needed to later match retrieved passages back to source page images).
    Short pages are merged with the next page (up to max_pages) so a chunk
    still has enough content to be useful for retrieval; a single very long
    page is kept as its own chunk rather than being split mid-page."""
    pages = extract_pdf_pages(text)
    offset = _printed_page_offset(pages)
    chunks: list[dict[str, str]] = []
    buffer_pages: list[int] = []
    buffer_text: list[str] = []

    def flush() -> None:
        if not buffer_pages:
            return
        combined = " ".join(buffer_text).strip()
        if combined:
            printed = [p - offset for p in buffer_pages if offset is not None and p - offset >= 1]
            chunks.append({
                "source": source,
                "text": combined,
                # PDF page index -- what image_map.json pages refer to.
                "page_range": _format_range(buffer_pages),
                # Number printed on the page itself, used for citations; empty
                # for front matter (cover, contents), which has no page number.
                "page_label": _format_range(printed) if printed else "",
            })

    def is_front_matter(page_number: int) -> bool:
        return offset is None or page_number - offset < 1

    for page_number, page_text in pages:
        # Don't merge front matter (contents, glossary) into the first body
        # page -- the chunk would be cited as page 1 but open with glossary text.
        if buffer_pages and is_front_matter(buffer_pages[-1]) != is_front_matter(page_number):
            flush()
            buffer_pages = []
            buffer_text = []
        buffer_pages.append(page_number)
        buffer_text.append(page_text)
        buffer_chars = sum(len(t) for t in buffer_text)
        if buffer_chars >= min_chars or len(buffer_pages) >= max_pages:
            flush()
            buffer_pages = []
            buffer_text = []

    flush()
    return chunks


IMAGE_MAP_PATH = APP_DIR / "image_map.json"


@dataclass
class ImageEntry:
    id: str
    chapter: int
    caption: str
    page: int
    file: str
    keywords: list[str]


def load_image_map(path: Path = IMAGE_MAP_PATH) -> list[ImageEntry]:
    """Load the curated figure/table manifest built by scripts/build_image_map.py.
    Missing or malformed files degrade to no images instead of breaking chat."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not load image map at %s: %s", path, exc)
        return []

    entries: list[ImageEntry] = []
    for item in raw:
        try:
            entries.append(
                ImageEntry(
                    id=str(item["id"]),
                    chapter=int(item.get("chapter", 0)),
                    caption=str(item.get("caption", "")),
                    page=int(item["page"]),
                    file=str(item["file"]),
                    keywords=[str(k) for k in item.get("keywords", [])],
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return entries


def _parse_page_range(page_range: str) -> tuple[int, int] | None:
    if not page_range:
        return None
    parts = page_range.split("-")
    try:
        if len(parts) == 1:
            page = int(parts[0])
            return page, page
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


# Descriptive or very frequent words in this textbook. On their own they don't
# say which figure fits a question -- "เปรียบเทียบ" is a keyword of both a
# comparator-circuit diagram and a number-base table -- so one generic hit
# isn't enough to show an image, but two generic hits or one specific are.
GENERIC_IMAGE_KEYWORDS = frozenset({
    "ข้อมูล", "ระบบ", "คอมพิวเตอร์", "การทำงาน", "หน่วย", "ประเภท", "สัญญาณ",
    "วงจร", "ตัวอย่าง", "ดิจิทัล", "แปลง", "โครงสร้าง", "รหัส", "พื้นฐาน",
    "ระดับ", "ผลลัพธ์", "การประมวลผล", "การสื่อสาร", "อินพุต", "ตาราง",
    "กระบวนการ", "ส่วนประกอบ", "องค์ประกอบ", "ขั้นตอน", "สัญลักษณ์",
    "เปรียบเทียบ", "ความสัมพันธ์", "คุณลักษณะ", "การแสดง", "การเขียน",
    "การแบ่งส่วน", "ช่วงเวลา", "ช่องทาง",
    "data", "model", "unit", "state", "input", "two",
})


def _keyword_in_question(keyword: str, lowered_question: str) -> bool:
    kw = keyword.lower()
    if kw.isascii():
        # Whole-word match for English, so "ip" doesn't fire inside "chip".
        # Thai has no word spacing, so Thai keywords stay substring matches.
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", lowered_question) is not None
    return kw in lowered_question


def _image_keyword_matches(keyword: str, lowered_question: str) -> bool:
    # A keyword also matches through its own synonym group ("RAM" <- "แรม").
    # Expanding the keyword side, not the question, keeps a broad group
    # member like "หน่วยความจำหลัก" from hitting other images' keywords.
    group = _SYNONYM_LOOKUP.get(keyword.lower(), (keyword,))
    return any(_keyword_in_question(term, lowered_question) for term in group)


def match_images_for_passages(
    passages: list[Passage],
    question: str,
    image_entries: list[ImageEntry],
    *,
    max_images: int,
) -> list[dict[str, Any]]:
    """Pick images to attach to a grounded answer. An image is only eligible
    when both hold: its source page falls inside the page range of one of the
    answer's grounding passages, AND its keywords match the question (at least
    one specific keyword, or at least two generic ones). Among eligible
    images, more specific hits rank first, then more generic hits."""
    if not image_entries:
        return []

    candidate_pages: set[int] = set()
    for passage in passages:
        bounds = _parse_page_range(passage.page_range)
        if bounds is None:
            continue
        start, end = bounds
        candidate_pages.update(range(start, end + 1))

    if not candidate_pages:
        return []

    lowered_question = question.strip().lower()

    scored: list[tuple[int, int, ImageEntry]] = []
    for entry in image_entries:
        if entry.page not in candidate_pages:
            continue
        specific = generic = 0
        for kw in entry.keywords:
            if kw and _image_keyword_matches(kw, lowered_question):
                if kw.lower() in GENERIC_IMAGE_KEYWORDS:
                    generic += 1
                else:
                    specific += 1
        if specific >= 1 or generic >= 2:
            scored.append((specific, generic, entry))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2].page, item[2].id))

    selected = [entry for _, _, entry in scored[:max_images]]
    return [
        {
            "id": entry.id,
            "caption": entry.caption,
            "page": entry.page,
            "file": entry.file,
        }
        for entry in selected
    ]


_QA_PATTERN = re.compile(
    r"-\s*\*\*Question:\*\*\s*(?P<question>.+?)\s*\n"
    r"-\s*\*\*Answer:\*\*\s*(?P<answer>.+?)(?=\n\n|\n###|\n##|\Z)",
    re.DOTALL,
)


def parse_qa_pairs(text: str, source: str) -> list[QAPair]:
    """Extract Question/Answer pairs from the "- **Question:** ... \\n
    - **Answer:** ..." markdown format our datasets use, so exact questions
    can be matched and answered verbatim instead of going through chunk
    retrieval + LLM paraphrasing."""
    pairs: list[QAPair] = []
    for match in _QA_PATTERN.finditer(text):
        question = " ".join(match.group("question").split())
        answer = " ".join(match.group("answer").split())
        if question and answer:
            pairs.append(QAPair(source=source, question=question, answer=answer))
    return pairs


def _embed_texts(texts: list[str], model: str, api_key: str) -> np.ndarray | None:
    """Embed a batch of texts with the Gemini embedding API. Returns None (instead of
    raising) on any failure so callers can fall back to TF-IDF-only retrieval."""
    if not texts or not api_key:
        return None
    client = genai.Client(api_key=api_key, http_options={"timeout": 45_000})
    # The free tier caps embedding at roughly 30k tokens/minute; 50 textbook
    # chunks is ~26k tokens, so one batch fits in a single minute's quota.
    batch_size = 50
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        try:
            response = client.models.embed_content(model=model, contents=batch)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Embedding batch failed (items %d-%d): %s", start, start + len(batch), exc)
            continue
        vectors.extend(embedding.values for embedding in response.embeddings)

    # Embeddings must line up row-for-row with the chunks, so any gap means
    # falling back to keyword-only rather than returning a partial matrix.
    if len(vectors) != len(texts):
        logger.warning(
            "Embedding request incomplete (%d/%d texts embedded), falling back to keyword-only retrieval",
            len(vectors), len(texts),
        )
        return None
    return np.array(vectors, dtype=np.float32)


def _cosine_scores(query_vector: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    query_norm = np.linalg.norm(query_vector)
    matrix_norms = np.linalg.norm(matrix, axis=1)
    denom = matrix_norms * query_norm
    denom[denom == 0] = 1e-9
    return (matrix @ query_vector) / denom


def data_signature() -> tuple[Any, ...]:
    signature = []
    pattern = str(DATA_DIR / "**" / "*")
    for raw_path in sorted(glob.glob(pattern, recursive=True)):
        path = Path(raw_path)
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            stat = path.stat()
            signature.append((str(path), stat.st_mtime, stat.st_size))
    return tuple(signature)


def build_index(signature: tuple[Any, ...], settings: Settings | None = None) -> RetrievalIndex:
    settings = settings or Settings()
    documents = load_documents()
    chunks: list[dict[str, str]] = []
    files: list[IndexedFile] = []
    qa_pairs: list[QAPair] = []
    for document in documents:
        if is_pdf_page_preservation_dataset(document.text):
            doc_chunks = chunk_pdf_pages(document.text, document.source)
        else:
            doc_chunks = chunk_text(document.text, document.source)
        chunks.extend(doc_chunks)
        qa_pairs.extend(parse_qa_pairs(document.text, document.source))
        files.append(
            IndexedFile(
                source=document.source,
                ext=document.ext,
                chars=len(document.text),
                chunks=len(doc_chunks),
            )
        )

    qa_vectorizer: TfidfVectorizer | None = None
    qa_matrix: Any = None
    if qa_pairs:
        qa_vectorizer = TfidfVectorizer(ngram_range=(1, 2))
        qa_matrix = qa_vectorizer.fit_transform([pair.question for pair in qa_pairs])

    if not chunks:
        return RetrievalIndex(
            signature=signature,
            chunks=[],
            word_vectorizer=None,
            char_vectorizer=None,
            matrix=None,
            embeddings=None,
            files=[],
            qa_pairs=qa_pairs,
            qa_vectorizer=qa_vectorizer,
            qa_matrix=qa_matrix,
        )

    texts = [chunk["text"] for chunk in chunks]
    word_vectorizer = TfidfVectorizer(ngram_range=(1, 2))
    char_vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(3, 5))
    word_matrix = word_vectorizer.fit_transform(texts)
    char_matrix = char_vectorizer.fit_transform(texts)
    matrix = hstack([word_matrix, char_matrix])

    # MIN_RELEVANCE is calibrated for TF-IDF-only scores; hybrid scores sit on a
    # much higher scale, so semantic must stay opt-in rather than switching on
    # whenever a key happens to have enough embedding quota.
    embeddings = None
    if settings.semantic_weight > 0:
        embeddings = _embed_texts(texts, settings.embedding_model, resolve_api_key("gemini"))

    return RetrievalIndex(
        signature=signature,
        chunks=chunks,
        word_vectorizer=word_vectorizer,
        char_vectorizer=char_vectorizer,
        matrix=matrix,
        embeddings=embeddings,
        files=sorted(files, key=lambda item: item.source),
        qa_pairs=qa_pairs,
        qa_vectorizer=qa_vectorizer,
        qa_matrix=qa_matrix,
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
        blocks.append(f"[แหล่งที่ {index} | {passage.citation}]\n{passage.text}")
    return "\n\n---\n\n".join(blocks)


def _social_pattern(token: str) -> re.Pattern[str]:
    # English signals must be whole words ("hi" must not fire on "while",
    # "graphic", "machine"); Thai has no word spaces, so Thai signals match as
    # substrings except where they sit inside a longer word ("บาย" in "อธิบาย").
    if token.isascii():
        return re.compile(rf"(?<![a-z]){re.escape(token)}(?![a-z])")
    if token == "บาย":
        return re.compile(r"(?<!อธิ)บาย")
    return re.compile(re.escape(token))


_SOCIAL_PATTERNS = {
    group: tuple(_social_pattern(token) for token in tokens)
    for group, tokens in {
        "bye": BYE_WORDS,
        "thanks": THANKS_WORDS,
        "greeting": GREETING_WORDS,
        "social": SOCIAL_PHRASES,
    }.items()
}
_POLITE_FILLER = re.compile(
    r"ครับ|ค่ะ|คะ|คับ|จ้า|จ้ะ|นะ|มากๆ|มาก|เลย|\byou\b|\bthere\b|\bso\b|\bmuch\b|\ba lot\b"
    r"|[\s.,!?~'\"()\-_]+"
)
# A message only counts as pure small talk when, after removing the social
# signal and polite filler, at most this many characters remain. Otherwise it
# carries a real question ("สวัสดีครับ RAM คืออะไร") and goes to retrieval.
_SOCIAL_LEFTOVER_LIMIT = 4


def _social_group(question: str) -> str | None:
    lowered = question.strip().lower()
    if not lowered:
        return None
    for group, patterns in _SOCIAL_PATTERNS.items():
        if any(pattern.search(lowered) for pattern in patterns):
            leftover = lowered
            for pats in _SOCIAL_PATTERNS.values():
                for pattern in pats:
                    leftover = pattern.sub("", leftover)
            leftover = _POLITE_FILLER.sub("", leftover)
            return group if len(leftover) <= _SOCIAL_LEFTOVER_LIMIT else None
    return None


def local_conversation_fallback(question: str, kb_files: list[str]) -> str:
    group = _social_group(question)
    if group == "bye":
        return "ได้เลยครับ ไว้คุยกันใหม่ ถ้ามีคำถามเรื่องพื้นฐานคอมพิวเตอร์ส่งมาได้เสมอครับ"
    if group == "thanks":
        return "ยินดีครับ ถ้ามีประเด็นไหนอยากให้ช่วยต่อ ถามมาได้เลย"
    if group == "greeting":
        return "สวัสดีครับ ผมคือ Polaris ถามเรื่องพื้นฐานคอมพิวเตอร์ได้เลยครับ"
    if group == "social":
        return (
            "ผมคือ Polaris ครับ ผู้ช่วยตอบคำถามเรื่องพื้นฐานคอมพิวเตอร์ "
            "โดยค้นหาจากตำราภาษาไทย 8 บท แล้วตอบพร้อมอ้างอิงเลขหน้าและรูปประกอบ"
        )
    if kb_files:
        return (
            "ผมยังหาเนื้อหาที่ตอบคำถามนี้ในตำราไม่เจอครับ "
            "ลองถามให้เจาะจงขึ้น หรือเลือกบทจากแถบข้างเพื่อดูคำถามตัวอย่างได้เลย"
        )
    return "ตอนนี้ระบบยังโหลดตำราไม่ได้ครับ กรุณาแจ้งผู้ดูแลระบบ"


def is_social_message(question: str) -> bool:
    return _social_group(question) is not None


# "คุณ" is also a prefix of ordinary words (คุณสมบัติ, คุณลักษณะ ...), and the
# bot reference must sit right next to the verb so textbook questions such as
# "ใครสร้างคอมพิวเตอร์เครื่องแรก" or "ช่วยบอกหน่อยว่าใครสร้าง ENIAC" don't match.
_BOT = r"(?:คุณ(?!สมบัติ|ภาพ|ลักษณะ|ค่า|ประโยชน์|ครู)|polaris|โพลาริส|แชทบอท|บอท|เธอ)"
_MAKE = r"(?:สร้าง|พัฒนา|ออกแบบ|จัดทำ|ทำ)"
_CREATOR_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"{_MAKE}\s*(?:ตัว)?{_BOT}",  # ใครสร้างคุณ, คนที่พัฒนา Polaris
        rf"{_BOT}\s*(?:ถูก|ได้รับการ)?\s*{_MAKE}\s*(?:ขึ้น(?:มา)?)?\s*(?:โดย|จาก)",  # คุณถูกสร้างโดยใคร
        rf"ผู้{_MAKE}\s*(?:ของ)?\s*{_BOT}",  # ผู้สร้างของคุณ
        rf"{_BOT}\s*(?:มี)?ใคร\s*เป็น\s*(?:คน|ผู้){_MAKE}",  # Polaris มีใครเป็นผู้พัฒนา
        r"\bwho\b.{0,20}\b(?:made|created?|built|developed|designed)\b.{0,10}\b(?:you|polaris)\b",
        r"\b(?:your|polaris'?s?)\s+(?:creators?|developers?|makers?|authors?)\b",
    )
)
_CREATOR_WHO = re.compile(r"ใคร|ผู้|คน|ทีม|\bwho\b|creator|developer|maker|author")


def is_creator_question(question: str) -> bool:
    lowered = question.strip().lower()
    return bool(_CREATOR_WHO.search(lowered)) and any(p.search(lowered) for p in _CREATOR_PATTERNS)


def build_grounded_prompt(question: str, passages: list[Passage], history: list[dict[str, str]] | None) -> str:
    return (
        "RECENT CONVERSATION:\n"
        f"{history_as_text(history)}\n\n"
        "DOCUMENT CONTEXT:\n"
        f"{build_context(passages)}\n\n"
        "USER QUESTION:\n"
        f"{question}\n\n"
        "Answer ONLY from the DOCUMENT CONTEXT above. Do not use outside knowledge."
        " If the context does not contain enough information, say so clearly."
    )


def build_conversation_prompt(question: str, history: list[dict[str, str]] | None) -> str:
    return (
        "RECENT CONVERSATION:\n"
        f"{history_as_text(history)}\n\n"
        "LATEST USER MESSAGE:\n"
        f"{question}"
    )


def build_web_prompt(question: str, history: list[dict[str, str]] | None, sources: list[WebSource]) -> str:
    blocks = [f"[{i}] {source.title} ({source.url})\n{source.text}" for i, source in enumerate(sources, 1)]
    results = "\n\n".join(blocks)
    return (
        f"WEB SEARCH RESULTS (Wikipedia, retrieved {time.strftime('%Y-%m-%d')}):\n"
        f"{results}\n\n"
        f"{build_conversation_prompt(question, history)}"
    )


def cited_web_sources(answer: str, sources: list[WebSource]) -> list[WebSource]:
    """Keep only the articles the answer names, so a stray search hit (e.g.
    "Monty Python" for a Python question) isn't shown as a source. Titles are
    compared without their disambiguation suffix: "Python (programming
    language)" counts as cited when the answer says "Python"."""
    lowered = answer.lower()
    if not sources or "wikipedia" not in lowered:
        return []
    cited: list[WebSource] = []
    seen_bases: set[str] = set()
    for source in sources:
        base = re.sub(r"\s*\([^)]*\)$", "", source.title).lower()
        # "IPhone (1st generation)" shares its base with "IPhone"; keep only
        # the higher-ranked one unless the answer names the full title.
        if base in seen_bases and source.title.lower() not in lowered:
            continue
        if source.title.lower() in lowered or base in lowered:
            cited.append(source)
            seen_bases.add(base)
    return cited or sources[:1]


def web_search_query(
    question: str,
    history: list[dict[str, str]],
    settings: Settings,
    typhoon_api_key: str,
    gemini_api_key: str,
) -> list[str]:
    """Ask an LLM for up to two English search terms; empty when the question
    shouldn't be searched (small talk, off-topic) or no provider answers.
    Typhoon goes first here: it's the faster, steadier of the two, and this
    step adds latency to every off-textbook answer. All attempts share one
    time budget: if no term arrives in time, skip the search and answer
    without it rather than make the user wait on a hanging provider."""
    prompt = build_conversation_prompt(question, history)
    deadline = time.monotonic() + SEARCH_QUERY_TIME_BUDGET
    for name, key in available_provider_candidates("typhoon", typhoon_api_key, gemini_api_key):
        remaining = deadline - time.monotonic()
        if remaining < 1.0:
            logger.warning("Search-query step ran out of time; answering without web search")
            break
        try:
            raw = _provider_instance(name, settings).conversation(
                api_key=key,
                prompt=prompt,
                system_instruction=SEARCH_QUERY_SYSTEM_PROMPT,
                temperature=0.0,
                history=None,
                timeout=remaining,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Search-query provider %s failed: %s", name, exc)
            continue
        line = raw.strip().splitlines()[0] if raw.strip() else ""
        terms = [term.strip(" \"'`.") for term in line.split("|")]
        terms = [term[:60] for term in terms if term and term.upper() != "NONE"]
        return terms[:2]
    return []


# Domain synonym pairs for this textbook's terminology. TF-IDF only matches
# shared surface words, so a question phrased with the English term, an
# abbreviation, or a colloquial Thai term misses passages that only use the
# textbook's own wording (and vice versa). Each group is expanded to every
# other term in the same group when building the retrieval query, without
# needing an external API call.
SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("cpu", "หน่วยประมวลผลกลาง", "ซีพียู", "หน่วยประมวลผล"),
    ("ram", "แรม", "หน่วยความจำหลัก", "หน่วยความจำชั่วคราว"),
    ("rom", "รอม"),
    ("gpu", "การ์ดจอ", "หน่วยประมวลผลกราฟิก"),
    ("flowchart", "ผังงาน", "โฟลว์ชาร์ต"),
    ("mouse", "เมาส์"),
    ("monitor", "จอภาพ", "จอแสดงผล"),
    ("keyboard", "คีย์บอร์ด", "แป้นพิมพ์"),
    ("printer", "เครื่องพิมพ์", "ปริ๊นเตอร์"),
    ("big data", "bigdata", "บิ๊กดาต้า", "ข้อมูลขนาดใหญ่"),
    ("flash drive", "แฟลชไดรฟ์", "แฟลชไดร์ฟ"),
    ("hard disk", "harddisk", "ฮาร์ดดิสก์", "จานบันทึกข้อมูล"),
    ("input device", "อุปกรณ์นำเข้าข้อมูล", "อุปกรณ์อินพุต"),
    ("output device", "อุปกรณ์แสดงผล", "อุปกรณ์เอาต์พุต"),
    ("binary code", "รหัสฐานสอง", "เลขฐานสอง"),
    ("gray code", "รหัสเกรย์"),
    ("ascii code", "รหัสแอสกี้", "แอสกี้"),
    ("parity bit", "พาริตี้บิต", "บิตพาริตี"),
    ("logic gate", "เกตลอจิก", "ลอจิกเกต", "เกต", "เกท", "gate"),
    ("digital logic", "ดิจิทัลลอจิก"),
    ("information technology", "เทคโนโลยีสารสนเทศ"),
    ("data communication", "การสื่อสารข้อมูล"),
    ("motherboard", "mainboard", "เมนบอร์ด", "แผงวงจรหลัก"),
    ("lan", "local area network", "เครือข่ายท้องถิ่น", "เครือข่ายแลน", "แลน"),
    ("algorithm", "อัลกอริทึม", "อัลกอริธึม"),
    ("pseudocode", "pseudo code", "รหัสเทียม"),
    ("operating system", "os", "ระบบปฏิบัติการ"),
)

# "คอม" is everyday shorthand for "คอมพิวเตอร์", but it can't be a normal
# synonym group: it's a substring of the full word and of unrelated words
# (คอมไพเลอร์, คอมโพเนนต์, คอมมานด์ ...), so it's matched with exclusions.
_KOM_SHORTHAND = re.compile(r"คอม(?!พิวเตอร์|ไพ|โพ|มาน|มิว|เมนต์|แพ)")

_SYNONYM_LOOKUP: dict[str, tuple[str, ...]] = {}
for _group in SYNONYM_GROUPS:
    for _term in _group:
        _SYNONYM_LOOKUP[_term.lower()] = _group


def expand_query_with_synonyms(query: str) -> str:
    """Append any synonym-group terms whose keyword appears in the query, so
    TF-IDF has surface-level overlap with passages that use different wording
    for the same concept. Longer terms are checked first so e.g. "hard disk"
    matches before a shorter unrelated substring could."""
    query = _KOM_SHORTHAND.sub("คอมพิวเตอร์", query)
    lowered = query.lower()
    additions: list[str] = []
    seen_groups: set[tuple[str, ...]] = set()
    for term in sorted(_SYNONYM_LOOKUP, key=len, reverse=True):
        if term in lowered:
            group = _SYNONYM_LOOKUP[term]
            if group in seen_groups:
                continue
            seen_groups.add(group)
            additions.extend(t for t in group if t.lower() != term)
    if not additions:
        return query
    return f"{query} {' '.join(additions)}"


class KnowledgeBase:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self._lock = threading.Lock()
        self._index = build_index(data_signature(), self.settings)
        self.image_entries = load_image_map()

    def refresh(self, force: bool = False) -> RetrievalIndex:
        signature = data_signature()
        with self._lock:
            if force or signature != self._index.signature:
                self._index = build_index(signature, self.settings)
            return self._index

    def current_index(self) -> RetrievalIndex:
        return self.refresh()

    def match_exact_qa(self, query: str) -> QAPair | None:
        """Find a dataset question that matches the user's question closely
        enough to answer with the dataset's own wording verbatim, instead of
        going through chunk retrieval + LLM paraphrasing. Returns None when no
        question clears the configured similarity threshold."""
        index = self.current_index()
        if not index.qa_pairs or index.qa_vectorizer is None:
            return None

        query_vector = index.qa_vectorizer.transform([query])
        scores = cosine_similarity(query_vector, index.qa_matrix)[0]
        best_idx = int(np.argmax(scores))
        best_score = float(scores[best_idx])
        if best_score < self.settings.exact_qa_threshold:
            return None
        return index.qa_pairs[best_idx]

    def retrieve(self, query: str, top_k: int | None = None) -> list[Passage]:
        index = self.current_index()
        if not index.chunks or index.word_vectorizer is None or index.char_vectorizer is None:
            return []

        effective_top_k = max(1, top_k or self.settings.top_k)
        expanded_query = expand_query_with_synonyms(query)
        word_query = index.word_vectorizer.transform([expanded_query])
        char_query = index.char_vectorizer.transform([expanded_query])
        query_vector = hstack([word_query, char_query])
        keyword_scores = cosine_similarity(query_vector, index.matrix)[0]

        if index.embeddings is not None:
            query_embedding = _embed_texts([query], self.settings.embedding_model, resolve_api_key("gemini"))
        else:
            query_embedding = None

        if query_embedding is not None:
            semantic_scores = _cosine_scores(query_embedding[0], index.embeddings)
            # Both score arrays are cosine similarities in [-1, 1] (in practice
            # mostly [0, 1]), so a plain weighted sum keeps them comparable
            # without needing separate normalization.
            weight = self.settings.semantic_weight
            scores = (1 - weight) * keyword_scores + weight * semantic_scores
        else:
            scores = keyword_scores

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
                    page_range=chunk.get("page_range", ""),
                    page_label=chunk.get("page_label", ""),
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

    def _client(self, api_key: str, timeout: float | None = None) -> OpenAI:
        # Bound the call so a slow/hanging Typhoon request fails fast enough
        # for the caller (or the auto-fallback logic) to react instead of
        # hanging until the deployment platform's own gateway times out.
        # max_retries=0 so a single slow attempt can't multiply the wall-clock
        # timeout (the SDK retries failed/timed-out requests by default).
        return OpenAI(
            api_key=api_key,
            base_url=self.settings.typhoon_base_url,
            timeout=timeout or 25.0,
            max_retries=0,
        )

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

    def conversation(self, *, api_key: str, prompt: str, system_instruction: str, temperature: float, history: list[dict[str, str]] | None, timeout: float | None = None) -> str:
        client = self._client(api_key, timeout)
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

    def _client(self, api_key: str, timeout: float | None = None) -> genai.Client:
        # Short timeout, no built-in retries: a hanging/high-demand Gemini
        # response should fail fast so the caller's fallback to the next
        # provider actually happens within the request's own time budget.
        timeout_ms = int((timeout or self.settings.gemini_timeout) * 1000)
        return genai.Client(api_key=api_key, http_options={"timeout": timeout_ms, "retry_options": {"attempts": 1}})

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

    def conversation(self, *, api_key: str, prompt: str, system_instruction: str, temperature: float, history: list[dict[str, str]] | None, timeout: float | None = None) -> str:
        client = self._client(api_key, timeout)
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
    if is_creator_question(question):
        return {
            "answer": CREATOR_ANSWER,
            "passages": [],
            "images": [],
            "elapsed": round(time.time() - started_at, 3),
            "mode": "assistant_fallback",
            "provider_used": "local",
        }
    social_only = is_social_message(question)
    if social_only:
        return {
            "answer": local_conversation_fallback(question, kb_files),
            "passages": [],
            "images": [],
            "elapsed": round(time.time() - started_at, 3),
            "mode": "assistant_fallback",
            "provider_used": "local",
        }

    exact_match = kb.match_exact_qa(question)
    if exact_match is not None:
        return {
            "answer": exact_match.answer,
            "passages": [
                {"source": exact_match.source, "text": exact_match.answer, "score": 1.0}
            ],
            "images": [],
            "elapsed": round(time.time() - started_at, 3),
            "mode": "exact_match",
            "provider_used": "dataset",
        }

    passages = kb.retrieve(question, top_k=top_k)

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
                    "passages": [passage.to_payload() for passage in passages],
                    "images": [],
                    "elapsed": round(time.time() - started_at, 3),
                    "mode": "needs_provider",
                    "provider_used": "none",
                }
            return {
                "answer": "ผมพบข้อมูลที่เกี่ยวข้องในเอกสารแล้ว แต่เชื่อมต่อโมเดลไม่สำเร็จในรอบนี้ครับ ลองใหม่อีกครั้งได้เลย",
                "passages": [passage.to_payload() for passage in passages],
                "images": [],
                "elapsed": round(time.time() - started_at, 3),
                "mode": "provider_error",
                "provider_used": "none",
            }

        # The retrieved passages can score above the relevance threshold while
        # still being off-topic for this specific question (TF-IDF matches on
        # shared words, not shared meaning). When that happens the grounded
        # provider itself declines per the system prompt -- fall through to
        # general computer knowledge instead of surfacing that refusal, same
        # as the "no passages retrieved" case below.
        if "ไม่พบข้อมูลที่เกี่ยวข้องในเอกสาร" not in answer:
            images = match_images_for_passages(
                passages, question, kb.image_entries, max_images=settings.max_images_per_answer
            )
            return {
                "answer": answer,
                "passages": [passage.to_payload() for passage in passages],
                "images": images,
                "elapsed": round(time.time() - started_at, 3),
                "mode": "grounded",
                "provider_used": provider_name,
            }

    # No usable passages in the dataset (either none retrieved, or the
    # grounded provider itself declined). Fall back to general computer
    # knowledge instead of an outright refusal -- the system prompt itself
    # still refuses anything unrelated to computers, and always discloses
    # that the answer isn't from the research documents.
    if not available_provider_candidates(conversation_choice, typhoon_api_key, gemini_api_key):
        return {
            "answer": "ตอนนี้ระบบยังไม่ได้ตั้งค่า API key ของ AI (Typhoon หรือ Gemini) จึงยังตอบคำถามนอกตำราไม่ได้ครับ กรุณาแจ้งผู้ดูแลระบบ",
            "passages": [],
            "images": [],
            "elapsed": round(time.time() - started_at, 3),
            "mode": "needs_provider",
            "provider_used": "none",
        }

    web_sources: list[WebSource] = []
    if settings.web_search == "wikipedia":
        for term in web_search_query(question, chat_history, settings, typhoon_api_key, gemini_api_key):
            for source in search_wikipedia(term):
                if source.url not in {s.url for s in web_sources}:
                    web_sources.append(source)
        web_sources = web_sources[:4]

    if web_sources:
        general_prompt = build_web_prompt(question, chat_history, web_sources)
    else:
        general_prompt = build_conversation_prompt(question, chat_history)
    system_instruction = general_computer_system_prompt(with_web_results=bool(web_sources))
    answer = ""
    provider_name = ""
    for candidate_name, candidate_key in available_provider_candidates(
        conversation_choice,
        typhoon_api_key,
        gemini_api_key,
    ):
        provider = _provider_instance(candidate_name, settings)
        try:
            answer = provider.conversation(
                api_key=candidate_key,
                prompt=general_prompt,
                system_instruction=system_instruction,
                temperature=temperature,
                history=chat_history,
            )
            provider_name = candidate_name
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning("General-knowledge provider %s failed: %s", candidate_name, exc)
            continue

    if not answer:
        return {
            "answer": "ขออภัยครับ เชื่อมต่อ AI ไม่สำเร็จในรอบนี้ ลองส่งคำถามใหม่อีกครั้งได้เลยครับ",
            "passages": [],
            "images": [],
            "elapsed": round(time.time() - started_at, 3),
            "mode": "provider_error",
            "provider_used": "none",
        }

    cited = cited_web_sources(answer, web_sources)
    return {
        "answer": answer,
        "passages": [],
        "images": [],
        "web_sources": [source.to_payload() for source in cited],
        "elapsed": round(time.time() - started_at, 3),
        "mode": "web_search" if cited else "conversation",
        "provider_used": provider_name,
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
