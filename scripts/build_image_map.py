"""One-time script: extract captioned content figures from the textbook PDF
into static/images/textbook/ and draft image_map.json for human review.

Run manually (not part of the running app):
    .venv/Scripts/python.exe scripts/build_image_map.py
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path

import pymupdf

PROJECT_DIR = Path(__file__).resolve().parent.parent
SOURCE_DIR = Path(r"D:\ai-chatbot\NEW_DataSET")
PDF_PATH = next(SOURCE_DIR.glob("*.pdf"))
MD_PATH = PROJECT_DIR / "data" / "computer-textbook-2567.md"
OUTPUT_IMAGE_DIR = PROJECT_DIR / "static" / "images" / "textbook"
OUTPUT_MAP_PATH = PROJECT_DIR / "image_map.json"

# Same PUA fix as rag_service.fix_thai_pua_marks, duplicated here so this
# script has no dependency on the running app's module.
PUA_FIX = {
    "\uf701": "\u0e34", "\uf702": "\u0e35", "\uf703": "\u0e36", "\uf704": "\u0e37",
    "\uf705": "\u0e48", "\uf706": "\u0e49", "\uf709": "\u0e4c", "\uf70a": "\u0e48",
    "\uf70b": "\u0e49", "\uf70c": "\u0e4a", "\uf70e": "\u0e4c", "\uf710": "\u0e31",
    "\uf712": "\u0e47", "\uf713": "\u0e48", "\uf714": "\u0e49", "\uf71d": "\u0e2c",
}
_PUA_PATTERN = re.compile("|".join(re.escape(k) for k in PUA_FIX))


def fix_thai_pua(text: str) -> str:
    return _PUA_PATTERN.sub(lambda m: PUA_FIX[m.group(0)], text)


PAGE_HEADING = re.compile(r"^### หน้า PDF (\d+)\s*$", re.MULTILINE)
IMAGE_ROW = re.compile(
    r"^\|\s*\d+\s*\|\s*(?P<xref>\d+)\s*\|\s*\d+x\d+\s*\|"
    r"[^|]*\|\s*`\[(?P<bbox>[^\]]+)\]`\s*\|\s*(?P<caption>[^|]*)\|\s*\[เปิดภาพ\][^|]*\|\s*$",
    re.MULTILINE,
)
FIGURE_CAPTION = re.compile(
    r"ภาพ(?:ที่)?\s*([๐-๙0-9]+)[-–]([๐-๙0-9]+)\s*(?:\(([ก-ฮ]+)\))?\s*(?:\((ต่อ)\))?\s*(?:แสดง\s*)?(.*)"
)
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
# Thai consonants used as figure sub-labels (ก, ข, ค, ...) mapped to ASCII
# letters, so generated filenames stay safe across filesystems/URLs.
THAI_SUB_LABELS = {ch: letter for ch, letter in zip("กขคงจฉชซฌญ", "abcdefghij")}

# Content figures/tables that don't follow the "ภาพที่ X-Y" caption pattern
# (some use a section-number heading instead, some are tables captioned
# "ตารางที่ X-Y", and one has no caption row at all) -- found by manually
# reviewing every image row the automatic pattern skipped. xrefs listed in
# the same top-to-bottom stacking order they appear in the PDF (matches
# group_split_figures' merge order for the auto-detected figures).
MANUAL_FIGURES = [
    {
        "id": "ch4-fig-algorithm",
        "chapter": 4,
        "figure_no": 0,  # not part of the book's own ภาพที่ numbering
        "caption": "โครงสร้างพื้นฐานที่ใช้ในการเขียนโปรแกรม",
        "page": 64,
        "xrefs": ["451"],
        "keywords": ["โครงสร้างพื้นฐานที่ใช้ในการเขียนโปรแกรม", "Algorithm"],
    },
    {
        "id": "ch6-fig-ecl-ic",
        "chapter": 6,
        "figure_no": 0,
        "caption": "ไอซีตระกูลอีซีแอล",
        "page": 138,
        "xrefs": ["802", "803"],
        "keywords": ["ไอซีตระกูลอีซีแอล", "ECL"],
    },
    {
        "id": "ch7-table1",
        "chapter": 7,
        "figure_no": 0,
        "caption": "ตารางที่ ๗-๑ เปรียบเทียบเลขฐานสิบ เลขฐานสิบหก เลขฐานสองและรหัส BCD",
        "page": 144,
        "xrefs": ["859", "860", "858"],
        "keywords": ["ตารางเปรียบเทียบเลขฐาน", "BCD", "เลขฐานสิบ", "เลขฐานสิบหก", "เลขฐานสอง"],
    },
    {
        "id": "ch7-fig-gray-example",
        "chapter": 7,
        "figure_no": 0,
        "caption": "ตัวอย่างการเปลี่ยนรหัสเกรย์ให้เป็นเลขฐานสอง",
        "page": 148,
        "xrefs": ["883", "882"],
        "keywords": ["รหัสเกรย์", "เลขฐานสอง"],
    },
    {
        "id": "ch7-table2",
        "chapter": 7,
        "figure_no": 0,
        "caption": "ตารางเปรียบเทียบรหัสเพิ่ม 3 กับรหัส BCD",
        "page": 151,
        "xrefs": ["909", "910"],
        "keywords": ["รหัสเพิ่ม 3", "Excess-3", "BCD"],
    },
]


def thai_num(s: str) -> str:
    return s.translate(THAI_DIGITS)


@dataclass
class ImageRow:
    xref: str
    bbox: tuple[float, float, float, float]
    caption_raw: str
    page: int


@dataclass
class FigureEntry:
    id: str
    chapter: int
    figure_no: int
    caption: str
    page: int
    file: str
    keywords: list[str]


def parse_image_rows(text: str) -> list[ImageRow]:
    headings = list(PAGE_HEADING.finditer(text))
    rows: list[ImageRow] = []
    for match in IMAGE_ROW.finditer(text):
        pos = match.start()
        page_number = None
        for heading in headings:
            if heading.start() <= pos:
                page_number = int(heading.group(1))
            else:
                break
        if page_number is None:
            continue
        bbox = tuple(float(v.strip()) for v in match.group("bbox").split(","))
        rows.append(
            ImageRow(
                xref=match.group("xref"),
                bbox=bbox,  # type: ignore[arg-type]
                caption_raw=match.group("caption").strip(),
                page=page_number,
            )
        )
    return rows


def group_split_figures(rows: list[ImageRow]) -> list[tuple[list[ImageRow], ImageRow]]:
    """Pair each captioned row with any adjacent uncaptioned rows on the same
    page that share the same x-range and whose y-range touches it (a figure
    the PDF extraction split into stacked pieces), so the final crop covers
    the whole figure instead of just the captioned bottom slice."""
    by_page: dict[int, list[ImageRow]] = {}
    for row in rows:
        by_page.setdefault(row.page, []).append(row)

    groups: list[tuple[list[ImageRow], ImageRow]] = []
    for page_rows in by_page.values():
        for row in page_rows:
            if not FIGURE_CAPTION.match(row.caption_raw):
                continue
            member = [row]
            x0, y0, x1, y1 = row.bbox
            changed = True
            while changed:
                changed = False
                for other in page_rows:
                    if other in member:
                        continue
                    if other.caption_raw and other is not row:
                        continue  # don't merge across two captioned figures
                    ox0, oy0, ox1, oy1 = other.bbox
                    same_x = abs(ox0 - x0) < 2 and abs(ox1 - x1) < 2
                    touches = abs(oy1 - y0) < 2 or abs(oy0 - y1) < 2
                    if same_x and touches:
                        member.append(other)
                        y0 = min(y0, oy0)
                        y1 = max(y1, oy1)
                        changed = True
            groups.append((member, row))
    return groups


def render_bbox(doc: pymupdf.Document, page_number: int, bbox: tuple[float, float, float, float], scale: float = 3.0) -> pymupdf.Pixmap:
    page = doc[page_number - 1]
    rect = pymupdf.Rect(*bbox)
    matrix = pymupdf.Matrix(scale, scale)
    return page.get_pixmap(matrix=matrix, clip=rect)


def main() -> None:
    print(f"Reading dataset markdown: {MD_PATH}")
    text = fix_thai_pua(MD_PATH.read_text(encoding="utf-8"))
    rows = parse_image_rows(text)
    print(f"Parsed {len(rows)} image rows from the reference table")

    groups = group_split_figures(rows)
    print(f"Found {len(groups)} captioned content figures (after merging split pieces)")

    OUTPUT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(str(PDF_PATH))

    entries: list[FigureEntry] = []
    seen_ids: dict[str, int] = {}
    for members, caption_row in groups:
        match = FIGURE_CAPTION.match(caption_row.caption_raw)
        chapter = int(thai_num(match.group(1)))
        figure_no = int(thai_num(match.group(2)))
        sub_label = match.group(3)  # e.g. "ก", "ข" for a figure split into labeled parts
        is_continuation = match.group(4) == "ต่อ"
        description = match.group(5).strip()

        xs0 = min(m.bbox[0] for m in members)
        ys0 = min(m.bbox[1] for m in members)
        xs1 = max(m.bbox[2] for m in members)
        ys1 = max(m.bbox[3] for m in members)
        combined_bbox = (xs0, ys0, xs1, ys1)

        figure_id = f"ch{chapter}-fig{figure_no}"
        if sub_label:
            figure_id += f"-{THAI_SUB_LABELS.get(sub_label, sub_label)}"
        if is_continuation:
            figure_id += "-cont"
        if figure_id in seen_ids:
            seen_ids[figure_id] += 1
            figure_id = f"{figure_id}-{seen_ids[figure_id]}"
        else:
            seen_ids[figure_id] = 1
        filename = f"{figure_id}.png"
        pix = render_bbox(doc, caption_row.page, combined_bbox)
        pix.save(str(OUTPUT_IMAGE_DIR / filename))

        keywords = [w for w in re.split(r"[\s,():./]+", description) if len(w) > 1]
        display_caption = f"{description} ({sub_label})" if sub_label else description

        entries.append(
            FigureEntry(
                id=figure_id,
                chapter=chapter,
                figure_no=figure_no,
                caption=display_caption,
                page=caption_row.page,
                file=f"static/images/textbook/{filename}",
                keywords=keywords,
            )
        )
        print(f"  saved {filename}  (page {caption_row.page}, {len(members)} piece(s)): {description}")

    by_xref = {row.xref: row for row in rows}
    print(f"\nAdding {len(MANUAL_FIGURES)} manually reviewed figures/tables that don't follow the ภาพที่ X-Y caption pattern")
    for manual in MANUAL_FIGURES:
        member_rows = [by_xref[xr] for xr in manual["xrefs"] if xr in by_xref]
        missing = [xr for xr in manual["xrefs"] if xr not in by_xref]
        if missing:
            print(f"  WARNING: {manual['id']} references missing xrefs {missing}, skipping")
            continue

        xs0 = min(r.bbox[0] for r in member_rows)
        ys0 = min(r.bbox[1] for r in member_rows)
        xs1 = max(r.bbox[2] for r in member_rows)
        ys1 = max(r.bbox[3] for r in member_rows)
        combined_bbox = (xs0, ys0, xs1, ys1)

        figure_id = manual["id"]
        filename = f"{figure_id}.png"
        pix = render_bbox(doc, manual["page"], combined_bbox)
        pix.save(str(OUTPUT_IMAGE_DIR / filename))

        entries.append(
            FigureEntry(
                id=figure_id,
                chapter=manual["chapter"],
                figure_no=manual["figure_no"],
                caption=manual["caption"],
                page=manual["page"],
                file=f"static/images/textbook/{filename}",
                keywords=manual["keywords"],
            )
        )
        print(f"  saved {filename}  (page {manual['page']}, {len(member_rows)} piece(s)): {manual['caption']}")

    doc.close()

    entries.sort(key=lambda e: (e.chapter, e.figure_no))
    OUTPUT_MAP_PATH.write_text(
        json.dumps([asdict(e) for e in entries], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {len(entries)} entries to {OUTPUT_MAP_PATH}")
    print(f"Images saved to {OUTPUT_IMAGE_DIR}")


if __name__ == "__main__":
    main()
