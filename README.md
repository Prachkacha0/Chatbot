# ChatBot-Research

ระบบ chatbot สำหรับตอบคำถามเกี่ยวกับการประกอบคอมพิวเตอร์ โดยใช้ชุดข้อมูลภาษาไทย (6 บท 626 คู่คำถาม-คำตอบ) เป็นฐานความรู้ ผสานระหว่าง RAG (Retrieval-Augmented Generation) และ LLM จาก 2 provider คือ Gemini และ Typhoon

## Features

- **RAG (hybrid retrieval)**: ค้นหาข้อมูลจาก knowledge base ด้วย TF-IDF (keyword) ผสาน semantic embedding (Gemini) แล้วส่ง context ให้ LLM ตอบ พร้อมแหล่งอ้างอิง — ถ้าไม่มี `GEMINI_API_KEY` หรือเรียก embedding ไม่สำเร็จ ระบบจะ fallback ไปใช้ TF-IDF อย่างเดียวอัตโนมัติ
- **Dual provider**: ใช้ Typhoon สำหรับคำถามอิงเอกสาร, Gemini สำหรับการสนทนาทั่วไป (ตั้งค่าได้)
- **Markdown rendering**: คำตอบ render markdown ได้ (bold, bullet, code block ฯลฯ)
- **Dark / light mode**: สลับโหมดสว่าง-มืด จำค่าไว้ใน localStorage
- **Typing indicator**: แสดง animation ระหว่างรอคำตอบ
- **Enter to send**: กด Enter ส่งข้อความ, Shift+Enter ขึ้นบรรทัดใหม่
- **Mobile sidebar**: ปุ่ม hamburger toggle sidebar บนหน้าจอเล็ก
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
| `CONVERSATION_PROVIDER` | `gemini` | provider สำหรับสนทนาทั่วไป (`gemini` / `typhoon` / `auto`) |
| `TYPHOON_MODEL` | `typhoon-v2.5-30b-a3b-instruct` | model id ของ Typhoon |
| `GEMINI_MODEL` | `gemini-3.5-flash` | model id ของ Gemini |
| `TYPHOON_BASE_URL` | `https://api.opentyphoon.ai/v1` | endpoint (OpenAI-compatible) |
| `TOP_K` | `5` | จำนวน chunks สูงสุดที่ดึงมา |
| `MIN_RELEVANCE` | `0.05` | คะแนนรวม (hybrid) ขั้นต่ำ |
| `EMBEDDING_MODEL` | `gemini-embedding-001` | model id สำหรับ semantic embedding |
| `SEMANTIC_WEIGHT` | `0.6` | น้ำหนักของ semantic score เทียบกับ TF-IDF (0 = keyword-only, 1 = semantic-only) |

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
| `POST` | `/api/reload` | โหลด knowledge base ใหม่ |
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
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
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
- Semantic embedding คำนวณครั้งเดียวตอน build index (cache ไว้ในหน่วยความจำ) และคำนวณ query embedding อีกครั้งต่อคำถาม — ถ้า Gemini API ไม่พร้อมใช้งาน (ไม่มี key, หมด quota, ฯลฯ) ระบบ log warning แล้ว fallback ไปใช้ TF-IDF อย่างเดียวโดยอัตโนมัติ ไม่ทำให้แอปล่ม
- `app.py` เก็บไว้เป็น legacy Streamlit prototype เท่านั้น ไม่ใช้งานแล้ว
