from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import os
from openai import OpenAI
from fastapi.responses import HTMLResponse # GET / için HTML yanıtı

# ----------------------------------------------------
# 1. BAŞLANGIÇ VE AI İSTEMCİSİ TANIMLAMA
# ----------------------------------------------------

# FastAPI Uygulamasını Başlat
app = FastAPI()

# Gelen istek gövdesinin yapısı (URL almak için)
class URLItem(BaseModel):
    url: str

# OpenAI istemcisini, ortam değişkeninden anahtarı alarak başlat
client = None
try:
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        client = OpenAI(api_key=openai_key)
        # Terminalde başlangıç mesajı gösterir
        print("✅ OpenAI İstemcisi başarıyla başlatıldı.") 
    else:
        print("⚠️ UYARI: OPENAI_API_KEY ortam değişkeni bulunamadı. Özetleme çalışmayacaktır.")
        
except Exception as e:
    # Başlangıçta hata olsa bile uygulamanın kapanmasını önler
    print(f"❌ HATA: OpenAI İstemcisi başlatılırken beklenmedik bir sorun oluştu: {e}") 
    client = None

# ----------------------------------------------------
# 2. METİN ÇIKARMA FONKSİYONU (Web Scraping)
# ----------------------------------------------------

def extract_medium_text(url: str) -> str:
    """Medium URL'sinden temiz metin içeriğini çeker."""
    # (Bu fonksiyon, requests ve BeautifulSoup kullanarak makaleyi çeker ve temizler.)
    # Basitlik için önceki tam kodunuzdaki extract_medium_text fonksiyonunun içeriği buraya gelir.
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=15)
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
# 3. YAPAY ZEKA ÖZETLEME FONKSİYONU
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
# 4. API UÇ NOKTALARI (ENDPOINTS)
# ----------------------------------------------------

# 4a. Çalışma Kontrolü (Sizin kodunuzdaki gibi)
@app.get("/alive")
def read_alive():
    return {"status": "Alive", "message": "FastAPI Works!"}

# 4b. Özetleme Uç Noktası
@app.post("/api/summarize")
async def summarize_endpoint(item: URLItem):
    """
    Verilen Medium URL'sinden metni çıkarır ve yapay zeka ile özetler.
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
    
    # 3. Başarı Durumu
    return {
        "status": "success",
        "url": item.url,
        "summary": summary,
        "original_text_length": len(extracted_text)
    }

# 4c. Kök Dizini Bilgi Sayfası (404 almamak için)
@app.get("/", response_class=HTMLResponse)
async def read_root_info():
    return """
    <html>
        <body>
            <h1>Medium Summarizer API Çalışıyor</h1>
            <p>API endpoint: <code>/api/summarize</code> (POST)</p>
            <p>Çalışma Kontrolü: <code>/alive</code> (GET)</p>
        </body>
    </html>
    """

# Not: Uvicorn bu dosyayı uvicorn app:app --reload komutuyla çalıştırmalıdır.