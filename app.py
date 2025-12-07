from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime

import requests
from bs4 import BeautifulSoup
import os

from dotenv import load_dotenv
load_dotenv()

print("DEBUG → GROQ_API_KEY =", os.environ.get("GROQ_API_KEY"))

from groq import Groq

# Groq Client
groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

from database import SessionLocal, Summary, create_db_tables

# -------------------------------------------------------------------
# FASTAPI INIT
# -------------------------------------------------------------------

create_db_tables()
app = FastAPI()

class URLItem(BaseModel):
    url: str

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# -------------------------------------------------------------------
# SCRAPERAPI MEDIUM SCRAPING
# -------------------------------------------------------------------

def extract_medium_text(url: str) -> str:
    api_key = os.environ.get("SCRAPER_API_KEY")
    if not api_key:
        return "Hata: SCRAPER_API_KEY eksik"

    proxy_url = f"http://api.scraperapi.com?api_key={api_key}&url={url}"

    try:
        response = requests.get(proxy_url, timeout=60)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.find("article")

        if not article:
            return "Hata: Medium makalesi bulunamadı."

        parts = [
            t.get_text(strip=True)
            for t in article.find_all(["p", "h1", "h2", "h3", "li"])
            if t.get_text(strip=True)
        ]

        full_text = "\n\n".join(parts)
        return full_text if len(full_text) > 50 else "Hata: Metin çok kısa."

    except Exception as e:
        return f"Hata: Medium alınamadı → {e}"

# -------------------------------------------------------------------
# GROQ AI SUMMARY
# -------------------------------------------------------------------

def summarize_text(text: str) -> str:

    if not groq_client:
        return "Hata: Groq yapılandırılmadı."

    try:
        response = groq_client.chat.completions.create(
            model="mixtral-8x7b-32768",
            messages=[
                {
                    "role": "system",
                    "content": "Sen profesyonel bir Türkçe özetleyicisin. Metni kısa, net ve maddeler halinde özetle."
                },
                {
                    "role": "user",
                    "content": f"Bu metni özetle:\n\n{text[:15000]}"
                }
            ]
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        return f"Hata: Groq özetleme başarısız → {e}"



# -------------------------------------------------------------------
# /api/summarize
# -------------------------------------------------------------------

@app.post("/api/summarize")
def summarize_endpoint(item: URLItem, db: Session = Depends(get_db)):

    if "medium.com" not in item.url.lower():
        raise HTTPException(status_code=400, detail="Geçerli Medium URL girin.")

    extracted = extract_medium_text(item.url)

    if extracted.startswith("Hata"):
        raise HTTPException(status_code=500, detail=extracted)

    summary = summarize_text(extracted)

    if summary.startswith("Hata"):
        raise HTTPException(status_code=500, detail=summary)

    db_entry = Summary(
        original_url=item.url,
        original_text_length=len(extracted),
        summary_text=summary,
        created_at=datetime.utcnow()
    )

    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)

    return {
        "status": "success",
        "summary": summary
    }

# -------------------------------------------------------------------
# Root
# -------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def root():
    return """
    <h2>Medium Summarizer (Groq Llama 3.1)</h2>
    <p>POST → /api/summarize</p>
    """
