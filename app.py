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
import random 
from openai import OpenAI
import stripe # Stripe Entegrasyonu için
from passlib.context import CryptContext # Mock şifreleme için

# Veritabanı importu: database.py dosyasından User modelini de çekiyoruz
from database import SessionLocal, Summary, User, create_db_tables 

# ----------------------------------------------------
# 1. BAŞLANGIÇ VE ORTAM AYARLARI
# ----------------------------------------------------

# Şifreleme (Parola hash'leme) aracı
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
# 3. VERİTABANI BAĞIMLILIĞI VE KULLANICI YÖNETİMİ
# ----------------------------------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Mock Kullanıcı Yetkilendirmesi (Gerçek kullanıcı olmadan test için)
def get_current_user(db: Session = Depends(get_db)):
    """API anahtarı kontrolü yerine, ilk kullanıcıyı döndürür."""
    user = db.query(User).filter(User.id == 1).first()
    
    if user is None:
        # Eğer kullanıcı yoksa, basit bir test kullanıcısı oluştur
        test_user = User(
            email="testuser@saas.com",
            hashed_password=pwd_context.hash("test1234"),
            remaining_summaries=10 # Ücretsiz deneme hakkı
        )
        db.add(test_user)
        db.commit()
        db.refresh(test_user)
        print("🎉 Yeni test kullanıcısı oluşturuldu.")
        return test_user
        
    return user

# ----------------------------------------------------
# 4. AI VE ÖDEME İSTEMCİLERİ
# ----------------------------------------------------

# AI İstemcisi
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

# STRIPE YAPILANDIRMASI
try:
    stripe_key = os.environ.get("STRIPE_SECRET_KEY")
    if stripe_key:
        stripe.api_key = stripe_key
        print("✅ Stripe İstemcisi başarıyla yapılandırıldı.")
    else:
        print("⚠️ UYARI: STRIPE_SECRET_KEY ortam değişkeni bulunamadı. Ödeme işlemleri çalışmayacaktır.")
except Exception as e:
    print(f"❌ HATA: Stripe yapılandırılırken beklenmedik bir sorun oluştu: {e}")


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
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept-Language': 'en-US,en;q=0.9,tr;q=0.8',
            'Referer': 'https://www.google.com/', 
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1', 
        }
        
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status() 

        soup = BeautifulSoup(response.content, 'html.parser')
        
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
# 7. API UÇ NOKTALARI
# ----------------------------------------------------

@app.post("/api/summarize")
async def summarize_endpoint(
    item: URLItem, 
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user) # KULLANICI BAĞIMLILIĞI EKLENDİ
):
    """
    Kullanıcının özetleme hakkını kontrol eder, makaleyi özetler ve kaydeder.
    """
    
    # 1. ÖZET HAKKI KONTROLÜ
    if current_user.remaining_summaries <= 0:
        raise HTTPException(
            status_code=402, # Payment Required
            detail=f"Özetleme hakkınız kalmamıştır. Lütfen aboneliğinizi yenileyin. Kullanıcı E-posta: {current_user.email}"
        )
    
    if "medium.com" not in item.url:
        raise HTTPException(status_code=400, detail="Lütfen geçerli bir Medium URL'si girin.")
    
    # 2. Metni Çıkar
    extracted_text = extract_medium_text(item.url)
    
    if extracted_text.startswith("Hata"):
        raise HTTPException(status_code=500, detail=f"Metin Çıkarma Hatası: {extracted_text.replace('Hata: ', '')}")
        
    # 3. Metni Özetle
    summary = summarize_text(extracted_text)
    
    if summary.startswith("Hata"):
        raise HTTPException(status_code=500, detail=f"Özetleme Hatası: {summary.replace('Hata: ', '')}")
    
    # 4. Özet Verisini Veritabanına Kaydet ve Hakkı Düşür
    db_summary = Summary(
        original_url=item.url,
        original_text_length=len(extracted_text),
        summary_text=summary,
        created_at=datetime.utcnow(),
        user_id=current_user.id # Hangi kullanıcının özetlediğini kaydet
    )
    db.add(db_summary)
    
    # Kullanıcı hakkını düşür
    current_user.remaining_summaries -= 1
    db.add(current_user)
    
    db.commit()
    db.refresh(db_summary) 
    
    # 5. Başarı Durumu
    return {
        "status": "success",
        "url": item.url,
        "summary": summary,
        "remaining_summaries": current_user.remaining_summaries # Kalan hakkı döndür
    }

@app.post("/api/subscribe")
async def create_subscription(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Ödeme işlemini simüle eder ve kullanıcının hakkını yeniler.
    """
    if not stripe.api_key:
         raise HTTPException(status_code=500, detail="Ödeme servisi (Stripe) yapılandırılmamış.")

    try:
        # Gerçek Stripe çağrısı burada olur. (Şu an mock ediyoruz.)
        
        current_user.remaining_summaries += 50 # 50 özet hakkı ekle
        db.add(current_user)
        db.commit()
        
        return {
            "status": "success", 
            "message": "Abonelik başarılı! 50 yeni özet hakkınız eklendi.",
            "remaining_summaries": current_user.remaining_summaries
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ödeme işlemi sırasında bir hata oluştu: {e}")


# ----------------------------------------------------
# 8. KÖK DİZİN ENDPOINT'LERİ VE GEÇMİŞ
# ----------------------------------------------------
    
@app.get("/api/summaries/")
def get_all_summaries(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """
    Kullanıcının sadece kendi özetlerini listeler.
    """
    # KRİTİK: Sadece oturum açmış kullanıcının özetlerini çeker
    summaries = db.query(Summary).filter(Summary.user_id == current_user.id).all()
    
    results = [
        {
            "id": s.id,
            "url": s.original_url,
            "summary_preview": s.summary_text[:50] + "...", 
            "created_at": s.created_at.isoformat()
        } 
        for s in summaries
    ]
    
    return {"status": "success", "data": results, "user_email": current_user.email, "remaining_summaries": current_user.remaining_summaries}


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