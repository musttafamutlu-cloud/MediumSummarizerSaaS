from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session
from datetime import datetime

# Uygulamanın çalışması için gerekli kütüphaneler
import requests
from bs4 import BeautifulSoup
import re
import os
from openai import OpenAI
import random # 403 hatasını çözmek için eklendi

# Veritabanı importu: database.py dosyasının app.py ile AYNI KLASÖRDE olması gerekir.
from database import SessionLocal, Summary, create_db_tables 

# ----------------------------------------------------
# 1. BAŞLANGIÇ VE ORTAM AYARLARI
# ----------------------------------------------------

create_db_tables() # Veritabanı tablolarını uygulama başlamadan oluştur
app = FastAPI()

# Gelen istek gövdesinin yapısı
class URLItem(BaseModel):
    url: str

# ----------------------------------------------------
# 2. CORS MİDDLEWARE EKLEME
# ----------------------------------------------------

origins = ["*"] 

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"], 
    allow_headers=["*"],
)

# ----------------------------------------------------
# 3. VERİTABANI BAĞIMLILIĞI
# ----------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------------------------------------------
# 4. AI İSTEMCİSİ TANIMLAMA
# ----------------------------------------------------

client = None
try:
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        client = OpenAI(api_key=openai_key)
        print("✅ OpenAI İstemcisi başarıyla başlatıldı.")
    else:
        print("⚠️ UYARI: OPENAI_API_KEY ortam değişkeni bulunamadı.")
except Exception as e:
    print(f"❌ HATA: OpenAI İstemcisi başlatılırken beklenmedik bir sorun oluştu: {e}")
    client = None

# ----------------------------------------------------
# 5. METİN ÇIKARMA FONKSİYONU (Web Scraping - 403 Çözümü)
# ----------------------------------------------------

def extract_medium_text(url: str) -> str:
    """Medium URL'sinden temiz metin içeriğini çeker (403 hatası için randomize başlıklar kullanılır)."""
    
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15'
    ]

    try:
        # Rastgele bir User-Agent seç ve diğer kapsamlı başlıkları ekle
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
            'Referer': 'https://www.google.com/', 
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1', 
        }
        
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status() # HTTP hatalarını (4xx, 5xx) burada yakalar

        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Medium makale içeriğini hedefleyen seçici
        content_block = soup.find('article') 
        
        if not content_block:
            content_block = soup.find('div', class_=re.compile(r'postArticle'))

        if not content_block:
             return "Hata: Makale içeriği bulunamadı. URL Medium makalesi değil veya site yapısı değişmiş olabilir."

        paragraphs = []
        for element in content_block.find_all(['p', 'h1', 'h2', 'h3', 'li']):
            text = element.get_text(strip=True)
            if text:
                if element.name.startswith('h'):
                    paragraphs.append(f"[{element.name.upper()}] {text}")
                else:
                    paragraphs.append(text)
        
        full_text = '\n\n'.join(paragraphs)
        
        return full_text if len(full_text) > 50 else "Hata: Çıkarılan metin çok kısa, muhtemelen makale değil veya boş."

    except requests.exceptions.RequestException as e:
        return f"Hata: URL erişimi başarısız oldu. Detay: {e}"
    except Exception as e:
        return f"Beklenmedik bir hata oluştu: {e}"

# ----------------------------------------------------
# 6. YAPAY ZEKA ÖZETLEME FONKSİYONU
# ----------------------------------------------------

def summarize_text(text: str) -> str:
    """OpenAI API'sini kullanarak verilen metni özetler."""
    if not client:
        return "Hata: Yapay Zeka servisi kullanılamıyor (API Anahtarı eksik/hatalı)."
    
    system_prompt = (
        "Sen, bir makale özetleme uzmanısın. Sana verilen uzun makale metnini al, "
        "en önemli noktaları içeren, akıcı ve bilgilendirici bir Türkçe özet oluştur. "
        "Özetin madde işaretleriyle (bullet points) ve en fazla 5-7 maddeden oluşmasını sağla."
    )
    
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo", 
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Lütfen aşağıdaki makaleyi özetle:\n\n{text[:12000]}"} 
            ],
            temperature=0.3
        )
        
        return response.choices[0].message.content.strip()
        
    except Exception as e:
        return f"Hata: OpenAI özetleme sırasında bir sorun oluştu. Detay: {e}"

# ----------------------------------------------------
# 7. API UÇ NOKTASI (ENDPOINT)
# ----------------------------------------------------

@app.post("/api/summarize")
async def summarize_endpoint(item: URLItem, db: Session = Depends(get_db)):
    """
    Verilen Medium URL'sinden metni çıkarır, özetler ve veritabanına kaydeder.
    """
    if "medium.com" not in item.url:
        raise HTTPException(status_code=400, detail="Lütfen geçerli bir Medium URL'si girin.")
    
    # 1. Metni Çıkar
    extracted_text = extract_medium_text(item.url)
    
    if extracted_text.startswith("Hata"):
        raise HTTPException(status_code=500, detail=f"Metin Çıkarma Hatası: {extracted_text.replace('Hata: ', '')}")
        
    # 2. Metni Özetle
    summary = summarize_text(extracted_text)
    
    if summary.startswith("Hata"):
        raise HTTPException(status_code=500, detail=f"Özetleme Hatası: {summary.replace('Hata: ', '')}")
    
    # 3. Özet Verisini Veritabanına Kaydet
    db_summary = Summary(
        original_url=item.url,
        original_text_length=len(extracted_text),
        summary_text=summary,
        created_at=datetime.utcnow()
    )
    db.add(db_summary)
    db.commit()
    db.refresh(db_summary) 
    
    # 4. Başarı Durumu
    return {
        "status": "success",
        "url": item.url,
        "summary": summary,
        "original_text_length": len(extracted_text),
        "summary_id": db_summary.id 
    }

# ----------------------------------------------------
# 8. KÖK DİZİN ENDPOINT'LERİ VE GEÇMİŞ
# ----------------------------------------------------

@app.get("/alive")
def read_alive():
    return {"status": "Alive", "message": "FastAPI Works!"}

@app.get("/", response_class=HTMLResponse)
async def read_root_info():
    return """
    <html>
        <body>
            <h1>Medium Summarizer API Çalışıyor</h1>
            <p>API endpoint: <code>/api/summarize</code> (POST)</p>
            <p>Frontend uygulaması için <code>index.html</code> dosyasını doğrudan tarayıcınızda açın.</p>
        </body>
    </html>
    """
    
@app.get("/api/summaries/")
def get_all_summaries(db: Session = Depends(get_db)):
    """
    Veritabanındaki tüm özetleri (geçici olarak) listeler.
    """
    summaries = db.query(Summary).all()
    
    results = [
        {
            "id": s.id,
            "url": s.original_url,
            "summary_preview": s.summary_text[:50] + "...", 
            "created_at": s.created_at.isoformat()
        } 
        for s in summaries
    ]
    
    return {"status": "success", "data": results}