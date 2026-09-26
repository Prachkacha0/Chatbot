"""One-time fixup: re-tokenize image_map.json's Thai keyword phrases into
individual words so question-time keyword matching can actually hit them.
The original extraction only split on whitespace/punctuation, so most Thai
captions stayed as one glued-together phrase (see build_image_map.py:241).
This script only rewrites the "keywords" field of each entry -- ids, files,
captions, and pages are left untouched.

Run manually: python scripts/retokenize_keywords.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from pythainlp.corpus import thai_stopwords
from pythainlp.corpus.common import thai_words
from pythainlp.tokenize import Tokenizer

PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGE_MAP_PATH = PROJECT_ROOT / "image_map.json"

STOPWORDS = thai_stopwords()
# Single-character particles/punctuation-ish tokens that survive tokenization
# but carry no search value on their own.
EXTRA_STOPWORDS = {"ๆ", "ๆ่", "-", "(", ")", ":", "ๆ", "฿", "ตัว", "จำนวน", "ประกอบด้วย", "สำหรับ"}

# Domain/transliterated technical terms the default newmm dictionary doesn't
# recognize as single words, so it mis-splits them into meaningless syllable
# fragments (e.g. "ลอจิก" -> "ลอ"/"จิก", "อินเวอร์เตอร์" -> "อิน"/"เวอร์"/"เตอร์").
# Registering them as a custom dictionary keeps them intact.
CUSTOM_WORDS = {
    "ลอจิก", "ฟลิปฟลอป", "รีจีสเตอร์", "บล็อกไดอะแกรม", "ไดอะแกรม",
    "อินเวอร์เตอร์", "แอนด์เกต", "อีซีแอล", "ดิจิทัลลอจิก",
    "เกต", "สวิตซ์", "วงจร",
    # Compounds that are only meaningful whole ("เลขฐานสิบหก" -> "หก" alone is noise).
    "เลขฐานสิบหก", "เลขฐาน", "รหัสเพิ่ม", "รหัสเกรย์", "สามสถานะ", "แรงดันตก",
    "แรงดันขึ้น", "พ่นหมึก", "เครื่องคำนวณ", "แบบจุด", "วงจรนับ", "ไมโครโปรเซสเซอร์",
}
_TOKENIZER = Tokenizer(custom_dict=set(thai_words()) | CUSTOM_WORDS, engine="newmm")


def is_thai(text: str) -> bool:
    return bool(re.search(r"[฀-๿]", text))


def tokenize_keyword(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    if not is_thai(raw):
        # English/numeric keywords (e.g. "CPU", "BCD", "Excess-3") are already
        # atomic -- keep as-is instead of running the Thai tokenizer on them.
        return [raw]

    tokens = _TOKENIZER.word_tokenize(raw)
    if all((t in STOPWORDS or t in EXTRA_STOPWORDS) for t in tokens):
        # The whole keyword is stopword(s) (e.g. a stray "หรือ") -- drop it
        # entirely instead of falling back to the raw, still-a-stopword text.
        return []

    cleaned: list[str] = []
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if token in STOPWORDS or token in EXTRA_STOPWORDS or token.isdigit():
            continue
        if len(token) <= 1 and is_thai(token):
            # Single Thai characters are almost never meaningful search terms
            # on their own (unlike single English letters like "C").
            continue
        cleaned.append(token)
    return cleaned or [raw]  # tokenizer found nothing usable -- keep the phrase whole


def main() -> None:
    entries = json.loads(IMAGE_MAP_PATH.read_text(encoding="utf-8"))

    changed = 0
    for entry in entries:
        original = entry["keywords"]
        expanded: list[str] = []
        seen: set[str] = set()
        for kw in original:
            for token in tokenize_keyword(kw):
                if token not in seen:
                    seen.add(token)
                    expanded.append(token)
        if expanded != original:
            changed += 1
        entry["keywords"] = expanded

    IMAGE_MAP_PATH.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Re-tokenized keywords for {changed}/{len(entries)} entries.")


if __name__ == "__main__":
    main()
