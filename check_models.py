from groq import Groq
import os
from dotenv import load_dotenv

# .env dosyasının tam yolu
env_path = r"C:\Users\musta\OneDrive\Masaüstü\saas1\.env"

print("ENV PATH =", env_path)
print("File exists? ->", os.path.exists(env_path))

# .env dosyasını tam path ile yükle
load_dotenv(env_path)

key = os.getenv("GROQ_API_KEY")
print("GROQ_API_KEY =", key)

client = Groq(api_key=key)

print("\n--- GROQ MODELS ---")
models = client.models.list()
for m in models.data:
    print(m.id)
