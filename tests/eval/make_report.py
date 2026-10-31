"""Build the round-3 Excel reports (class set 35+6 and general-user 30) with
rounds 1-2 beside each question.

usage: python tests/eval/make_report.py RESULTS.json OUT_DIR --tested-on "TEXT"

RESULTS.json comes from run_local.py or run_render.py (needs eval35, extra6
and user30). Verdicts come from grades.py; for the general-user set the
script also checks them against the answer mode, so a re-run whose answers
changed doesn't silently keep stale grades.
"""
import argparse
import json
import re
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

sys.path.insert(0, str(Path(__file__).resolve().parent))
import grades as g  # noqa: E402

TEXTBOOK = ("grounded", "exact_match")

thin = Side(style="thin", color="999999")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
WRAP = Alignment(wrap_text=True, vertical="top")
CENTER = Alignment(horizontal="center", vertical="center", wrap_text=True)
HEAD = PatternFill("solid", fgColor="1E5E3A")
GREEN = PatternFill("solid", fgColor="D9EAD3")
RED = PatternFill("solid", fgColor="F4CCCC")
BETTER = PatternFill("solid", fgColor="CFE2F3")
WORSE = PatternFill("solid", fgColor="FCE5CD")
TICK = Font(name="Segoe UI Symbol", size=18)


def sheet(ws, headers, widths):
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = HEAD
        cell.alignment = CENTER
        cell.border = BORDER
    for col, width in zip("ABCDEFGHIJK", widths):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"


def add_row(ws, values, tick_cols, center_cols, history_cols, verdict):
    ws.append(values)
    row = ws.max_row
    for col in range(1, len(values) + 1):
        cell = ws.cell(row=row, column=col)
        cell.border = BORDER
        cell.alignment = CENTER if col in center_cols else WRAP
    for k, col in enumerate(tick_cols):
        ws.cell(row=row, column=col).font = TICK
        ws.cell(row=row, column=col).fill = GREEN if k < 2 else RED
    # Earlier-round cells: blue where this round fixed it, orange where it got worse.
    good = ("TP", "FN")
    for col in history_cols:
        cell = ws.cell(row=row, column=col)
        if cell.value != verdict:
            cell.fill = BETTER if verdict in good else WORSE


def ticks(verdict):
    return ["☑" if verdict == k else "☐" for k in ("TP", "TN", "FN", "FP")]


def clean(answer):
    return re.sub(r"\*\*(.+?)\*\*", r"\1", answer or "").strip()


def summary(wb, title, rows):
    ws = wb.create_sheet(title)
    for row in rows:
        ws.append(list(row))
    for row in ws.iter_rows():
        row[0].font = Font(bold=True)
        for cell in row:
            cell.alignment = WRAP
            cell.border = BORDER
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 60


def count(verdicts):
    return {k: sum(v == k for v in verdicts) for k in ("TP", "TN", "FN", "FP")}


def arrow(*values):
    return "  →  ".join(str(v) for v in values)


def general_note(row):
    if row["inside"]:
        pages = [p for p in row.get("pages") or [] if p]
        return f"ตอบจากตำรา ({pages[0]})" if pages else "ตอบจากตำรา"
    if row["mode"] == "web_search":
        titles = ", ".join(row.get("web") or [])
        return f"นอกตำรา บอกว่าไม่มีในตำรา แล้วค้น Wikipedia ({titles})"
    if row["mode"] == "assistant_fallback":
        return "ทักทาย/ขอบคุณ ตอบกลับทันทีโดยไม่ค้นตำรา"
    if "เฉพาะเรื่องคอมพิวเตอร์" in (row["answer"] or ""):
        return "ไม่ใช่เรื่องคอมพิวเตอร์ ปฏิเสธอย่างสุภาพ"
    return "นอกตำรา บอกว่าไม่มีในตำรา แล้วตอบตามความรู้ทั่วไป"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("results")
    parser.add_argument("out_dir")
    parser.add_argument("--tested-on", required=True, help="where/when round 3 ran, for the summary sheet")
    args = parser.parse_args()
    data = json.load(open(args.results, encoding="utf-8"))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    failed = [r["question"] for name in ("eval35", "extra6", "user30") for r in data[name]
              if r["mode"] in ("provider_error", None)]
    if failed:
        raise SystemExit(f"re-run these first (AI provider failed): {failed}")

    rounds = [
        ("รอบ 1", "6 ต.ค. 2569 บน Render (ก่อนแก้)"),
        ("รอบ 2", "8 ต.ค. 2569 บน Render (แก้บั๊กคำทักทาย, MIN_RELEVANCE 0.06, ถามต่อเนื่อง, เลขหน้าอ้างอิง)"),
        ("รอบ 3", f"{args.tested_on} (แก้ระดับ 3: คำพ้อง/คำหายาก, คำถามซื้อของ, คำค้น Wikipedia, หั่นตำราตามหัวข้อย่อย)"),
    ]

    # ---------- file 1: class set 35 + extras ----------
    wb = Workbook()
    ws = wb.active
    ws.title = "ผลทดสอบรอบ 3"
    headers = ["ลำดับ", "คำถาม", "คำตอบ (รอบ 3)", "TP", "TN", "FN", "FP", "รอบ 1", "รอบ 2", "หมายเหตุ (รอบ 3)"]
    widths = (7, 36, 80, 7, 7, 7, 7, 8, 8, 58)
    sheet(ws, headers, widths)
    v1s, v2s, v3s = [], [], []
    for row in data["eval35"]:
        no = row["no"]
        v1, v2 = g.R1_EVAL35[no][0], g.R2_EVAL35[no][0]
        v3, note = g.R3_EVAL35[no]
        if v3 == "TP" and row["mode"] not in TEXTBOOK:
            raise SystemExit(f"Q{no} graded TP but answered in mode {row['mode']}; re-grade it")
        v1s.append(v1); v2s.append(v2); v3s.append(v3)
        add_row(ws, [no, row["question"], clean(row["answer"]), *ticks(v3), v1, v2, note],
                tick_cols=(4, 5, 6, 7), center_cols=(1, 4, 5, 6, 7, 8, 9), history_cols=(8, 9), verdict=v3)

    ex = wb.create_sheet("คำถามเพิ่มเติม 36-41")
    sheet(ex, headers, widths)
    e1, e2, e3 = [], [], []
    for (no, v1, v2, _), (_, v3, note), row in zip(g.R1R2_EXTRA6, g.R3_EXTRA6, data["extra6"]):
        e1.append(v1); e2.append(v2); e3.append(v3)
        add_row(ex, [no, row["question"], clean(row["answer"]), *ticks(v3), v1, v2, note],
                tick_cols=(4, 5, 6, 7), center_cols=(1, 4, 5, 6, 7, 8, 9), history_cols=(8, 9), verdict=v3)

    c1, c2, c3 = count(v1s), count(v2s), count(v3s)
    x1, x2, x3 = count(e1), count(e2), count(e3)
    summary(wb, "สรุปเทียบรอบ 1-2-3", [
        ("หัวข้อที่ทดสอบ", "บทที่ 3 หัวข้อที่ 4 – บทที่ 4 หัวข้อที่ 7 (ตำราหน้า ๔๔–๕๘)"),
        *rounds,
        ("", ""),
        ("35 ข้อหลัก", "รอบ 1  →  รอบ 2  →  รอบ 3"),
        ("TP (ถามตรง ตอบตรง dataset)", arrow(c1["TP"], c2["TP"], c3["TP"])),
        ("TN (ถามตรง ไม่ตอบตรง dataset)", arrow(c1["TN"], c2["TN"], c3["TN"])),
        ("อัตราตอบถูก", arrow(*(f"{c['TP'] / 35:.1%}" for c in (c1, c2, c3)))),
        ("", ""),
        ("คำถามเพิ่มเติม 36-41", "รอบ 1  →  รอบ 2  →  รอบ 3"),
        ("TP", arrow(x1["TP"], x2["TP"], x3["TP"])),
        ("TN", arrow(x1["TN"], x2["TN"], x3["TN"])),
        ("", ""),
        ("สีในช่อง รอบ 1 / รอบ 2", "ฟ้า = รอบ 3 ตอบถูกแล้ว, ส้ม = รอบ 3 แย่ลง"),
    ])
    path1 = out_dir / "ผลทดสอบ-บท3-4-รอบ3.xlsx"
    wb.save(path1)

    # ---------- file 2: general-user 30 ----------
    wb = Workbook()
    ws = wb.active
    ws.title = "ผลทดสอบรอบ 3"
    sheet(ws, ["ลำดับ", "คำถาม", "ในตำรา?", "คำตอบ (รอบ 3)", "TP", "TN", "FN", "FP", "รอบ 1", "รอบ 2", "หมายเหตุ (รอบ 3)"],
          (7, 32, 9, 76, 7, 7, 7, 7, 8, 8, 52))
    u1, u2, u3 = [], [], []
    for row in data["user30"]:
        no, grounded = row["no"], row["mode"] in TEXTBOOK
        if row["inside"]:
            v1 = "TN" if no in g.R1_USER30_TN else "TP"
            v2 = "TN" if no in g.R2_USER30_TN else "TP"
            v3 = "TN" if no in g.R3_USER30_TN or not grounded else "TP"
        else:
            v1 = v2 = "FN"
            v3 = "FP" if grounded else "FN"
        u1.append(v1); u2.append(v2); u3.append(v3)
        note = g.R3_USER30_NOTES.get(no) or general_note(row)
        add_row(ws, [no, row["question"], "ใน" if row["inside"] else "นอก", clean(row["answer"]), *ticks(v3), v1, v2, note],
                tick_cols=(5, 6, 7, 8), center_cols=(1, 3, 5, 6, 7, 8, 9, 10), history_cols=(9, 10), verdict=v3)
    k1, k2, k3 = count(u1), count(u2), count(u3)
    summary(wb, "สรุปเทียบรอบ 1-2-3", [
        ("รูปแบบ", "สมมุติเป็นผู้ใช้งานทั่วไป ถามทั้งในและนอกตำรา (ใน 15 / นอก 15)"),
        *rounds,
        ("", "รอบ 1  →  รอบ 2  →  รอบ 3"),
        ("TP (ถามตรง ตอบตรง dataset)", arrow(k1["TP"], k2["TP"], k3["TP"])),
        ("TN (ถามตรง ไม่ตอบตรง dataset)", arrow(k1["TN"], k2["TN"], k3["TN"])),
        ("FN (ถามไม่ตรง ตอบไม่ตรง)", arrow(k1["FN"], k2["FN"], k3["FN"])),
        ("FP (ถามไม่ตรง ตอบตรง)", arrow(k1["FP"], k2["FP"], k3["FP"])),
        ("ตอบถูกต้อง (TP + FN) / 30", arrow(*(f"{(k['TP'] + k['FN']) / 30:.1%}" for k in (k1, k2, k3)))),
        ("", ""),
        ("หมายเหตุข้อ 17", "รอบ 3 ตรวจละเอียดขึ้น พบว่าคำตอบเรื่อง Big Data ไม่ได้มาจากตำรา (ดูหมายเหตุในตาราง)"),
    ])
    path2 = out_dir / "ผลทดสอบ-ผู้ใช้ทั่วไป-30ข้อ-รอบ3.xlsx"
    wb.save(path2)

    print(f"35: {c1} -> {c2} -> {c3}\nextra: {x1} -> {x2} -> {x3}\nuser30: {k1} -> {k2} -> {k3}")
    print(f"saved {path1}\nsaved {path2}")


if __name__ == "__main__":
    main()
