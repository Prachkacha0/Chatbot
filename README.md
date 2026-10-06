# Polaris

ระบบ chatbot สำหรับตอบคำถามเกี่ยวกับพื้นฐานคอมพิวเตอร์ โดยใช้ตำราภาษาไทย (8 บท) เป็นฐานความรู้ ผสานระหว่าง RAG (Retrieval-Augmented Generation) และ LLM จาก 2 provider คือ Gemini และ Typhoon

## Features

- **RAG retrieval**: ค้นหาข้อมูลจาก knowledge base ด้วย TF-IDF (keyword) พร้อมขยายคำค้นด้วยพจนานุกรมคำพ้องความหมาย แล้วส่ง context ให้ LLM ตอบ พร้อมแหล่งอ้างอิง — รองรับ semantic embedding (Gemini) เป็นตัวเลือกเสริมผ่าน `SEMANTIC_WEIGHT` (ปิดไว้เป็นค่าเริ่มต้น)
- **Dual provider**: Typhoon เป็นตัวหลักทั้งคำถามอิงเอกสารและคำถามนอกตำรา, Gemini เป็นตัวสำรองเมื่อ Typhoon ใช้ไม่ได้ (ตั้งค่าได้)
- **Markdown rendering**: คำตอบ render markdown ได้ (bold, bullet, code block ฯลฯ)
- **Dark / light mode**: สลับโหมดสว่าง-มืด จำค่าไว้ใน localStorage
- **ความกว้างของแชท**: ปุ่มตั้งค่าที่แถบบน เลือก แคบ (680px) / กลาง (900px) / กว้าง (1200px) จำค่าไว้ใน localStorage (ซ่อนบนจอมือถือเพราะแชทเต็มจออยู่แล้ว)
- **Typing indicator**: แสดง animation ระหว่างรอคำตอบ
- **Enter to send**: กด Enter ส่งข้อความ, Shift+Enter ขึ้นบรรทัดใหม่
- **ข้อมูลปัจจุบันสำหรับคำถามนอกตำรา**: ถ้าหาคำตอบในตำราไม่เจอ ระบบให้ LLM แปลงคำถามเป็นคำค้นภาษาอังกฤษ แล้วค้น Wikipedia (ฟรี ไม่ต้องมี key) ส่งบทนำของบทความให้ LLM สรุป พร้อมแสดงลิงก์แหล่งที่มา คำถามที่ตอบจากตำราไม่ค้นเว็บ ถ้าค้นไม่สำเร็จจะตอบจากความรู้ของโมเดลพร้อมคำเตือนว่าข้อมูลอาจไม่เป็นปัจจุบัน
- **ประวัติแชท + แชทใหม่**: sidebar แสดงรายการแชทแยกตามวัน กดเปิดแชทเก่าต่อได้ ลบได้ (มีถามยืนยัน) เก็บใน localStorage ของเบราว์เซอร์เท่านั้น สูงสุด 20 แชท เกินแล้วแชทเก่าสุดถูกลบอัตโนมัติ แต่ละแชทแยก context กัน (ส่งประวัติ 8 ข้อความล่าสุดของแชทนั้นให้ LLM)
- **เลย์เอาต์เต็มจอแบบแอปแชท**: แถบข้าง (โลโก้, แชทใหม่, ประวัติแชท) ชิดซ้ายสูงเต็มจอ พื้นที่แชทกินส่วนที่เหลือ ซ่อน/แสดงแถบข้างได้ด้วยปุ่ม ☰ (จอคอมจำค่าไว้ ตอนซ่อนปุ่ม ☰ กับโลโก้ย้ายไปหัวแชท, มือถือเป็น drawer เลื่อนออกมา)
- **สารบัญ 8 บทแบบป๊อปอัป**: ปุ่มรูปหนังสือในช่องพิมพ์ กดบทเพื่อใส่คำถามตัวอย่าง
- **ช่องพิมพ์**: ทรงแคปซูลขยายตามข้อความ ปุ่มส่งอยู่ในช่อง ลบแชทได้จากปุ่มถังขยะในแถบข้าง (มีถามยืนยัน)
- **คำตอบเรื่องผู้สร้าง**: ถามว่าใครสร้าง/พัฒนา Polaris จะได้รายชื่อผู้จัดทำแบบตายตัว (`CREATOR_ANSWER` ใน `rag_service.py`) ไม่ผ่าน LLM ส่วนคำถามอย่าง "ใครสร้างคอมพิวเตอร์เครื่องแรก" ยังค้นจากตำราตามปกติ
- **Rate limiting**: จำกัด 10 requests/นาที ต่อ IP ที่ `/api/chat`
- **Error state**: แสดง error bubble สีแดงแยกจากคำตอบปกติ
- **Source citations**: แสดงแหล่งอ้างอิงพับได้ใต้คำตอบ

## Main files

```text
Chatbot/
├── main.py              # FastAPI web app + rate limiting
├── rag_service.py       # RAG pipeline + Gemini/Typhoon provider routing
├── templates/index.html # Chat UI (Jinja2)
├── static/app.css       # Styles + dark mode
├── static/app.js        # Frontend logic
├── requirements.txt
├── .env                 # API keys (ไม่ commit)
├── .env.example         # Template
├── render.yaml          # Render deploy config
└── data/                # ไฟล์ความรู้ (.txt, .md, .json, .pdf)
```

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

เปิดไฟล์ `.env` แล้วใส่ API key:

```text
TYPHOON_API_KEY=sk-...
GEMINI_API_KEY=AIza...
```

เปิด server:

```powershell
uvicorn main:app --reload --port 5001
```

เปิดเบราว์เซอร์:

```text
http://localhost:5001
```

## Environment variables

| Variable | Default | คำอธิบาย |
|---|---|---|
| `TYPHOON_API_KEY` | — | API key จาก opentyphoon.ai |
| `GEMINI_API_KEY` | — | API key จาก Google AI Studio |
| `GROUNDED_PROVIDER` | `typhoon` | provider สำหรับคำถามอิงเอกสาร (`gemini` / `typhoon` / `auto`) |
| `CONVERSATION_PROVIDER` | `typhoon` | provider สำหรับสนทนาทั่วไป (`gemini` / `typhoon` / `auto`) |
| `TYPHOON_MODEL` | `typhoon-v2.5-30b-a3b-instruct` | model id ของ Typhoon |
| `GEMINI_MODEL` | `gemini-3.6-flash` | model id ของ Gemini |
| `WEB_SEARCH` | `wikipedia` | ค้นข้อมูลปัจจุบันสำหรับคำถามนอกตำรา (`wikipedia` / `off`) |
| `GEMINI_TIMEOUT` | `12` | วินาทีที่รอ Gemini ก่อนสลับไปใช้ Typhoon (กันคำตอบค้างนานตอน Gemini ล่ม/คนใช้เยอะ) |
| `TYPHOON_BASE_URL` | `https://api.opentyphoon.ai/v1` | endpoint (OpenAI-compatible) |
| `TOP_K` | `5` | จำนวน chunks สูงสุดที่ดึงมา |
| `MIN_RELEVANCE` | `0.06` | คะแนนรวม (hybrid) ขั้นต่ำ — ตั้งต่ำเพราะหน้าตำราที่เขียนเป็นหัวข้อสั้นๆ หลายเรื่อง (เช่น ตำราหน้า ๕๑–๕๖) ได้คะแนนแค่ราว 0.06–0.10 แม้เป็นหน้าที่ถูก ส่วนเนื้อหาที่ไม่ตรงคำถาม prompt ของคำตอบอิงตำราจะปฏิเสธเอง |
| `MAX_IMAGES_PER_ANSWER` | `2` | จำนวนรูปจากตำราสูงสุดที่แนบกับคำตอบหนึ่งข้อ (`0` = ไม่แนบรูป) |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | model id สำหรับ semantic embedding |
| `SEMANTIC_WEIGHT` | `0` | น้ำหนักของ semantic score เทียบกับ TF-IDF (0 = keyword-only, 1 = semantic-only) — ปิดไว้เป็นค่าเริ่มต้น ถ้าเปิดต้องปรับ `MIN_RELEVANCE` ใหม่ด้วย เพราะคะแนน hybrid อยู่คนละสเกลกับ TF-IDF |

## Provider behavior

- **Grounded answers**: เมื่อพบ chunks ที่เกี่ยวข้องใน knowledge base, ใช้ provider ที่กำหนดใน `GROUNDED_PROVIDER`
- **General chat**: เมื่อไม่พบ chunks หรือคำถามเป็นเรื่องทั่วไป, ใช้ `CONVERSATION_PROVIDER`
- `auto` มีความหมายเดียวกับ `gemini` (Gemini ก่อน, fallback ไป Typhoon ถ้าใช้ไม่ได้)
- ถ้าไม่มี API key ทั้งสองตัว, ระบบตอบด้วย lightweight local response แทน

## API endpoints

| Method | Path | คำอธิบาย |
|---|---|---|
| `GET` | `/` | Chat UI |
| `POST` | `/api/chat` | ส่งคำถาม (rate-limited: 10/min) |
| `GET` | `/api/status` | สถานะ knowledge base |
| `GET` | `/health` | health check |

## Supported file types

`.txt` · `.md` · `.json` · `.pdf`

## Deploy to Render

1. Push repo ไป GitHub
2. ใน Render สร้าง **Web Service** จาก repo
3. Render อ่าน [`render.yaml`](./render.yaml) อัตโนมัติ หรือตั้งเอง:

```text
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips='*'
Health Check Path: /health
```

4. เพิ่ม environment variables ใน Render dashboard อย่างน้อย:

```text
TYPHOON_API_KEY=...
GEMINI_API_KEY=...
```

5. Deploy แล้วเปิด URL ที่ Render ให้

> **หมายเหตุ**: knowledge base โหลดจาก `data/` ในตัว app ถ้าเพิ่มเอกสารใหม่ต้อง commit แล้ว redeploy

## Notes

- Source citation ใช้ path สัมพัทธ์จาก `data/` ทำให้ชื่อไฟล์ซ้ำกันไม่ชน
- TF-IDF ใช้ทั้ง word n-grams และ character n-grams เพื่อ matching ที่ดีขึ้น
- Semantic embedding (เมื่อตั้ง `SEMANTIC_WEIGHT` > 0) คำนวณครั้งเดียวตอน build index (cache ไว้ในหน่วยความจำ) และคำนวณ query embedding อีกครั้งต่อคำถาม — ถ้า Gemini API ไม่พร้อมใช้งาน (ไม่มี key, หมด quota, ฯลฯ) ระบบ log warning แล้ว fallback ไปใช้ TF-IDF อย่างเดียวโดยอัตโนมัติ ไม่ทำให้แอปล่ม (free tier มีโควต้าราว 30,000 token/นาที ไม่พอ embed ตำราทั้งเล่มในครั้งเดียว)