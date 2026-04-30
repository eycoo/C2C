# FinVibe

Pencatatan keuangan UMKM otomatis via WhatsApp. Kirim pesan teks, voice note, atau foto bukti transfer — sistem langsung catat dan buat laporan.

**AI engine**: Groq API (llama-3.1-8b-instant + whisper-large-v3-turbo + llama-4-scout-17b-16e-instruct)

## Quick Start

```bash
pip install -r requirements.txt
cp .env.example .env   # isi API key kamu
uvicorn app.main:app --reload
```

Dashboard: http://localhost:8000/dashboard

## Mendapatkan Groq API Key

1. Buka https://console.groq.com/keys
2. Login atau buat akun
3. Buat API key baru
4. Salin ke `.env` sebagai `GROQ_API_KEY=...`

## Environment Variables

| Variable | Keterangan |
|----------|------------|
| `GROQ_API_KEY` | Groq API key |
| `VERIFY_TOKEN` | String bebas untuk verifikasi webhook Meta |
| `WHATSAPP_TOKEN` | Meta Graph API token (hanya untuk audio WhatsApp asli) |

## Endpoints

| Method | Path | Keterangan |
|--------|------|------------|
| GET | `/dashboard` | Demo UI interaktif |
| GET | `/` | Health check |
| GET | `/webhook` | Verifikasi webhook Meta |
| POST | `/webhook` | Handler pesan WhatsApp masuk |
| POST | `/send` | Input teks langsung (dipakai dashboard) |
| POST | `/send-audio` | Upload audio base64 → Whisper → NER |
| POST | `/send-image` | Upload gambar base64 → OCR bukti transfer |
| GET | `/transactions/{phone}` | Riwayat transaksi JSON |
| GET | `/report/{phone}` | Download laporan PDF |

## ngrok (untuk webhook WhatsApp asli)

```bash
ngrok http 8000
# Salin URL HTTPS ke Meta App Dashboard sebagai webhook URL
# Path webhook: /webhook
# Isi VERIFY_TOKEN yang sama di .env dan Meta dashboard
```

## Test dengan curl

Verifikasi webhook:
```bash
curl "http://localhost:8000/webhook?hub.mode=subscribe&hub.verify_token=c2c_verify&hub.challenge=12345"
```

Kirim pesan langsung:
```bash
curl -X POST http://localhost:8000/send \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "628123456789", "message": "habis 20rb buat makan siang"}'
```

Upload bukti transfer (gambar):
```bash
# Encode gambar ke base64 dulu
B64=$(base64 -w 0 bukti_transfer.jpg)
curl -X POST http://localhost:8000/send-image \
  -H "Content-Type: application/json" \
  -d "{\"phone_number\": \"628123456789\", \"image_b64\": \"$B64\", \"mime_type\": \"image/jpeg\"}"
```

Simulasi payload WhatsApp:
```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "entry": [{
      "changes": [{
        "value": {
          "messages": [{
            "from": "628123456789",
            "type": "text",
            "text": { "body": "terima transfer 500 ribu dari Budi buat pesanan kue" }
          }]
        }
      }]
    }]
  }'
```

Download laporan PDF:
```bash
curl http://localhost:8000/report/628123456789 -o report.pdf
```

## Cek database

```bash
sqlite3 app.db "SELECT * FROM transactions;"
```

## Alur sistem

```
Dashboard UI  ->  POST /send        ->  Groq LLM (NER)              ->  SQLite  ->  Reply
              ->  POST /send-audio  ->  Groq Whisper (ASR)  ->  NER  ->  SQLite  ->  Reply
              ->  POST /send-image  ->  Groq Vision (OCR)            ->  SQLite  ->  Reply

WhatsApp      ->  POST /webhook
  text        ->  Groq LLM (NER)              ->  SQLite  ->  Reply
  audio       ->  Groq Whisper (ASR)  ->  NER ->  SQLite  ->  Reply
  image       ->  (dashboard upload recommended)

GET /report/{phone}  ->  SQLite  ->  ReportLab PDF
```
