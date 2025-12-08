from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from fastapi.responses import HTMLResponse
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv

from groq import Groq

# -------------------------------------------------------------
# .env yükle
# -------------------------------------------------------------
env_path = r"C:\Users\musta\OneDrive\Masaüstü\saas1\.env"
load_dotenv(env_path)

# -------------------------------------------------------------
# DATABASE
# -------------------------------------------------------------
from database import SessionLocal, Summary, create_db_tables

create_db_tables()
app = FastAPI()


class URLItem(BaseModel):
    url: str


# -------------------------------------------------------------
# CORS
# -------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------------------
# DB DEP
# -------------------------------------------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -------------------------------------------------------------
# GROQ CLIENT
# -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

if not GROQ_API_KEY:
    raise RuntimeError("GROQ_API_KEY Bulunamadı!")

groq_client = Groq(api_key=GROQ_API_KEY)

print("🔥 GROQ AKTİF MODEL:", "llama-3.1-8b-instant")


# -------------------------------------------------------------
# SCRAPERAPI - MEDIUM SCRAPER
# -------------------------------------------------------------
def extract_medium_text(url: str) -> str:
    api_key = os.getenv("SCRAPER_API_KEY")
    if not api_key:
        return "Hata: SCRAPER_API_KEY eksik!"

    proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}"

    try:
        response = requests.get(proxy_url, timeout=60)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.find("article")
        if not article:
            return "Hata: Yazı bulunamadı."

        parts = []
        for tag in article.find_all(["p", "h1", "h2", "h3", "li"]):
            t = tag.get_text(strip=True)
            if t:
                parts.append(t)

        full_text = "\n\n".join(parts)
        return full_text if len(full_text) > 50 else "Hata: Metin çok kısa."

    except Exception as e:
        return f"Hata: Medium alınamadı → {e}"


# -------------------------------------------------------------
# GROQ SUMMARY
# -------------------------------------------------------------
def summarize_text(text: str) -> str:
    try:
        response = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Sen profesyonel bir özetleyicisin."},
                {"role": "user",
                 "content": f"Aşağıdaki metni Türkçe, kısa ve maddeler halinde özetle:\n\n{text[:15000]}"}
            ],
            temperature=0.3,
            max_tokens=512
        )

        # 🔥 Doğru erişim şekli (Groq objesi)
        return response.choices[0].message.content

    except Exception as e:
        return f"Hata: Groq özetleme başarısız → {e}"


# -------------------------------------------------------------
# ENDPOINT
# -------------------------------------------------------------
@app.post("/api/summarize")
def summarize_endpoint(item: URLItem, db: Session = Depends(get_db)):
    if "medium.com" not in item.url.lower():
        raise HTTPException(400, "Lütfen Medium URL girin.")

    extracted = extract_medium_text(item.url)
    if extracted.startswith("Hata"):
        raise HTTPException(500, extracted)

    summary = summarize_text(extracted)
    if summary.startswith("Hata"):
        raise HTTPException(500, summary)

    db_entry = Summary(
        original_url=item.url,
        original_text_length=len(extracted),
        summary_text=summary,
        created_at=datetime.utcnow()
    )
    db.add(db_entry)
    db.commit()

    return {"status": "success", "summary": summary}


# -------------------------------------------------------------
# ROOT
# -------------------------------------------------------------
@app.get("/")
def root():
    return {"status": "OK", "message": "Groq Summarizer çalışıyor!"}
