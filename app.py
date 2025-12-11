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
from groq import Groq

from database import SessionLocal, Summary, create_db_tables

# ----------------------------
# LOAD ENV
# ----------------------------
load_dotenv()

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

print("SCRAPER KEY:", SCRAPER_API_KEY)
print("GROQ KEY:", GROQ_API_KEY)

# ----------------------------
# GROQ CLIENT
# ----------------------------
groq_client = Groq(api_key=GROQ_API_KEY)

# ----------------------------
# FASTAPI SETUP
# ----------------------------
create_db_tables()
app = FastAPI()

class URLItem(BaseModel):
    url: str


# ----------------------------
# CORS
# ----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------
# DB CONNECTOR
# ----------------------------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ----------------------------
# SCRAPERAPI → MEDIUM SCRAPING
# ----------------------------
def extract_medium_text(url: str) -> str:
    if not SCRAPER_API_KEY:
        return "Hata: SCRAPER_API_KEY bulunamadı."

    proxy_url = f"http://api.scraperapi.com/?api_key={SCRAPER_API_KEY}&url={url}"

    try:
        response = requests.get(proxy_url, timeout=60)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        article = soup.find("article")

        if not article:
            return "Hata: Medium makalesi bulunamadı."

        parts = []
        for tag in article.find_all(["p", "h1", "h2", "h3", "li"]):
            text = tag.get_text(strip=True)
            if text:
                parts.append(text)

        full_text = "\n\n".join(parts)
        return full_text if len(full_text) > 50 else "Hata: Çıkarılan metin çok kısa."

    except Exception as e:
        return f"Hata: Medium alınamadı → {e}"


# ----------------------------
# GROQ → SUMMARIZER
# ----------------------------
def summarize_text(text: str) -> str:
    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "Summarize the following text in English in short bullet points."},
                {"role": "user", "content": text[:15000]},
            ]
        )

        # 🔥 DOĞRU ERİŞİM
        return completion.choices[0].message.content

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hata: Groq özetleme başarısız → {e}")



# ----------------------------
# POST /api/summarize
# ----------------------------
@app.post("/api/summarize")
def summarize_endpoint(item: URLItem, db: Session = Depends(get_db)):

    if "medium.com" not in item.url.lower():
        raise HTTPException(status_code=400, detail="Please enter a valid Medium URL.")

    extracted = extract_medium_text(item.url)
    if extracted.startswith("Hata"):
        raise HTTPException(status_code=500, detail=extracted)

    summary = summarize_text(extracted)

    db_entry = Summary(
        original_url=item.url,
        original_text_length=len(extracted),
        summary_text=summary,
        created_at=datetime.utcnow()
    )

    db.add(db_entry)
    db.commit()
    db.refresh(db_entry)

    return {"status": "success", "url": item.url, "summary": summary}


# ----------------------------
# GET HISTORY
# ----------------------------
@app.get("/api/history")
def get_history(db: Session = Depends(get_db)):

    items = db.query(Summary).order_by(Summary.id.desc()).all()

    return [
        {
            "id": item.id,
            "original_url": item.original_url,
            "summary_text": item.summary_text,
            "created_at": item.created_at.isoformat()
        }
        for item in items
    ]


# ----------------------------
# DELETE /api/delete/{id}
# ----------------------------
@app.delete("/api/delete/{item_id}")
def delete_summary(item_id: int, db: Session = Depends(get_db)):

    item = db.query(Summary).filter(Summary.id == item_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(item)
    db.commit()
    return {"status": "deleted"}


# ----------------------------
# ROOT
# ----------------------------
@app.get("/")
def root():
    return {"status": "OK", "message": "Medium Summarizer API running 🎉"}

