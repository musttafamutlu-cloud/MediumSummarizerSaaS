from sqlalchemy import create_engine, Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime

# ----------------------------------------------------
# 1. VERİTABANI AYARLARI
# ----------------------------------------------------

# SQLite veritabanı dosyası proje kök dizininde olacak
SQLALCHEMY_DATABASE_URL = "sqlite:///./summaries.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# Veritabanı oturumunu (SessionLocal) oluşturma
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Temel sınıf (Base) ile ORM modellerimizi oluşturacağız
Base = declarative_base()

# ----------------------------------------------------
# 2. VERİTABANI MODELLERİ (TABLO YAPILARI)
# ----------------------------------------------------

class Summary(Base):
    """Özetlenen makalelerin veritabanı modeli (tablosu)."""
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    original_url = Column(String, index=True)
    original_text_length = Column(Integer)
    summary_text = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Şu an kullanıcı girişi yapmadığımız için nullable=True (boş bırakılabilir)
    user_id = Column(Integer, nullable=True) 

# ----------------------------------------------------
# 3. TABLOLARI OLUŞTURMA FONKSİYONU
# ----------------------------------------------------

def create_db_tables():
    """Veritabanı dosyasını ve tabloları oluşturur."""
    # Base içindeki tüm modelleri (Summary) veritabanına yansıtır
    Base.metadata.create_all(bind=engine)