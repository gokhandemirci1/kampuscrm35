# Giriş Sorunları Giderme Rehberi

## Yaygın Sorunlar ve Çözümleri

### 1. "Incorrect email or password" Hatası

**Olası Sebepler:**
- Database henüz başlatılmamış
- Kullanıcı henüz oluşturulmamış

**Çözüm:**
1. API health endpoint'ini kontrol edin: `GET /api/health`
2. Database'in başlatıldığından emin olun
3. Vercel deployment'dan sonra ilk API çağrısı database'i başlatacaktır

### 2. "Sunucuya bağlanılamadı" Hatası

**Olası Sebepler:**
- API base URL'i yanlış
- CORS sorunu
- Backend çalışmıyor

**Çözüm:**
1. Browser console'da Network tab'ını kontrol edin
2. API base URL'inin doğru olduğundan emin olun (varsayılan: `/api`)
3. CORS ayarlarını kontrol edin

### 3. Local Development'ta Test

```bash
# Backend'i başlatın
cd api
python -m uvicorn main:app --reload --port 8000

# Frontend'i başlatın (yeni terminal)
npm run dev
```

API'nin çalıştığını test etmek için:
- `http://localhost:8000/` - API root
- `http://localhost:8000/api/health` - Health check
- `http://localhost:8000/api/login` - Login endpoint (POST)

### 4. Vercel Deployment'ta Test

1. Vercel Dashboard > Functions Logs'u kontrol edin
2. `https://your-app.vercel.app/api/health` endpoint'ini test edin
3. Database'in başlatıldığından emin olun

### 5. Test Kullanıcıları

Varsayılan kullanıcılar:
- **Email:** `gokhan@kampus.com`
- **Şifre:** `QWQD$(u~p3`

Veya:
- **Email:** `emre@kampus.com`
- **Şifre:** `Fco6hgVch2`

### 6. Database Başlatma (Manuel)

Eğer database başlatılmamışsa:

```python
# Python terminal'de
from api.database import init_db
init_db()
```

Veya:
```bash
cd api
python -c "from database import init_db; init_db()"
```

### 7. Browser Console Kontrolleri

1. Browser Developer Tools'u açın (F12)
2. Console tab'ına gidin
3. Login işlemi sırasında hataları kontrol edin
4. Network tab'ında API isteklerini kontrol edin

### 8. API Base URL Kontrolü

Frontend'de API base URL:
- Local development: `/api` (Vite proxy kullanır)
- Production: `/api` (Vercel routes ile yönlendirilir)

Eğer farklı bir URL kullanıyorsanız, `.env` dosyası oluşturun:
```
VITE_API_URL=http://localhost:8000/api
```

