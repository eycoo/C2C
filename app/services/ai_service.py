import base64
import json
import os

import httpx
from groq import Groq

from app.schemas import TransactionResult

_client: Groq | None = None
TEXT_MODEL = "llama-3.1-8b-instant"
AUDIO_MODEL = "whisper-large-v3-turbo"
VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _get_client() -> Groq:
    global _client
    if _client is None:
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


SYSTEM_PROMPT = """Kamu adalah parser transaksi keuangan untuk pesan WhatsApp UMKM Indonesia.

Output: JSON valid saja, tanpa teks lain.

{
  "intent": "expense | income | unknown",
  "amount": number,
  "category": string,
  "description": string
}

Aturan amount (Rupiah, integer):
- "rb" / "ribu" / "k" = dikali 1.000 → "20rb"=20000, "100rb"=100000, "500rb"=500000
- "jt" / "juta" = dikali 1.000.000 → "1.5jt"=1500000, "2jt"=2000000
- "ratus" = dikali 100 → "5 ratus"=500
- angka polos = nilai asli → "2000"=2000
- JANGAN mengalikan rb lagi — rb sudah berarti ribu (1.000), BUKAN ratus ribu

EXPENSE — hanya jika pesan mengandung sinyal pengeluaran eksplisit:
beli, bayar, bayarin, habis, keluar, keluarin, belanja, jajan, isi, top up,
kasih ke, transfer ke, kirim ke, langganan, sewa, cicilan, ongkos, gajiin

INCOME — hanya jika pesan mengandung sinyal pemasukan eksplisit:
terima, dapat, dapet, masuk, jual, jualan, laku, dibayar, dibayarin,
dp, omset, pemasukan, transfer dari, kirim dari, dari [nama orang]

UNKNOWN — gunakan ini jika:
- tidak ada sinyal eksplisit di atas
- pesan hanya berisi nama barang + nominal tanpa kata kerja (contoh: "tahu 2000", "bensin 50rb", "kopi 10rb")
- sapaan, pertanyaan, atau bukan transaksi
- JANGAN menebak intent jika ragu — pilih unknown, set amount = 0

category: food, transport, sales, supplies, utilities, salary, rent, dll
description: ringkasan singkat bahasa Indonesia berdasarkan isi pesan"""


def analyze_message(user_text: str) -> TransactionResult:
    response = _get_client().chat.completions.create(
        model=TEXT_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0,
    )
    data = json.loads(response.choices[0].message.content)
    return TransactionResult(
        intent=str(data.get("intent", "unknown")),
        amount=int(data.get("amount", 0)),
        category=str(data.get("category", "")),
        description=str(data.get("description", "")),
    )


def transcribe_audio(media_url: str) -> str:
    token = os.getenv("WHATSAPP_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"}

    with httpx.Client(timeout=30) as http:
        resp = http.get(media_url, headers=headers)
        resp.raise_for_status()
        audio_bytes = resp.content

    transcription = _get_client().audio.transcriptions.create(
        file=("audio.ogg", audio_bytes, "audio/ogg"),
        model=AUDIO_MODEL,
        language="id",
    )
    return transcription.text


def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/webm") -> str:
    clean_mime = mime_type.split(";")[0].strip()
    ext = clean_mime.split("/")[-1]
    ext_map = {"webm": "webm", "ogg": "ogg", "oga": "ogg", "mp4": "mp4",
               "mpeg": "mp3", "mpga": "mp3", "wav": "wav", "m4a": "m4a"}
    filename = f"audio.{ext_map.get(ext, 'webm')}"
    transcription = _get_client().audio.transcriptions.create(
        file=(filename, audio_bytes, clean_mime),
        model=AUDIO_MODEL,
        language="id",
    )
    return transcription.text


CONVERSATION_PROMPT = """Kamu asisten pencatat transaksi WhatsApp Business UMKM Indonesia.
Percakapan antara PENJUAL (role="saya") dan pihak lain (role="lawan": bisa pembeli atau supplier).

Output JSON valid saja:
{
  "action": "record | skip",
  "intent": "income | expense | null",
  "amount": number,
  "category": string,
  "description": string,
  "reply": string
}

=== ATURAN INTENT (paling penting) ===

PENENTU: SIAPA yang mengatakan konfirmasi bayar di pesan terakhir:

  role="lawan" bilang "udah transfer/bayar" ke kita
    → uang MASUK ke penjual → intent="income", kategori="sales"
    → contoh: "udah transfer 200rb ya kak", "sudah saya bayar"

  role="saya" bilang "udah transfer/bayar" ke lawan
    → uang KELUAR dari penjual → intent="expense"
    → contoh: "udah aku transfer 250rb ya", "sudah kubayar"
    → kategori: supplies (bahan), transport, salary, utilities, dll

JANGAN terbalik. Transfer dari saya = pengeluaran. Transfer dari lawan ke saya = pemasukan.

=== ATURAN ACTION ===

action="record" hanya jika SEMUA terpenuhi:
1. Pesan terakhir = konfirmasi pembayaran selesai (transfer, bayar, lunas, cair)
2. Nominal sudah jelas di percakapan (dari pesan ini atau sebelumnya)
3. Belum ada di list "transaksi tercatat" → jangan double

action="skip" jika:
- Negosiasi, tanya harga, tanya stok, sapaan
- Nominal belum disepakati
- Sudah tercatat sebelumnya

=== REPLY ===

reply: 1 kalimat natural Bahasa Indonesia informal ke lawan bicara.
- action="record" → konfirmasi singkat (contoh: "Siap, sudah tercatat ya!")
- action="skip", pesan butuh respons → balas relevan dan singkat
- action="skip", tidak perlu balas → return ""

=== AMOUNT ===
- "rb"/"ribu"/"k" = x1.000 → "100rb"=100000, "250rb"=250000
- "jt"/"juta" = x1.000.000 → "1.5jt"=1500000
- angka polos = nilai asli"""


def analyze_conversation(history: list[dict], recorded: list[dict]) -> dict:
    history_text = "\n".join(f"[{m['role']}]: {m['content']}" for m in history)
    recorded_text = (
        "\n".join(f"- {r.get('description', '-')} (Rp {r.get('amount', 0)})" for r in recorded)
        if recorded else "(belum ada)"
    )
    user_content = (
        f"Percakapan:\n{history_text}\n\n"
        f"Transaksi sudah tercatat di percakapan ini:\n{recorded_text}\n\n"
        "Analisis pesan TERAKHIR. Output JSON sesuai schema."
    )
    resp = _get_client().chat.completions.create(
        model=TEXT_MODEL,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": CONVERSATION_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return {
        "action": str(data.get("action", "skip")),
        "intent": data.get("intent"),
        "amount": int(data.get("amount", 0) or 0),
        "category": str(data.get("category", "")),
        "description": str(data.get("description", "")),
        "reply": str(data.get("reply", "")),
    }


VISION_PROMPT = """Kamu OCR khusus bukti pembayaran m-banking Indonesia (BCA, Mandiri, BRI, BNI,
CIMB, Permata, GoPay, OVO, DANA, ShopeePay, LinkAja, QRIS, dll).

Output: JSON valid saja, tanpa teks lain.

{
  "is_receipt": boolean,
  "status": "success | pending | failed | unknown",
  "amount": number,
  "sender_name": string,
  "recipient_name": string,
  "bank_or_app": string,
  "timestamp": string,
  "ref_no": string
}

Aturan:
- is_receipt=false jika gambar bukan bukti transfer/pembayaran (foto orang, makanan, dll).
  Set semua field lain ke nilai default (amount=0, string kosong).
- amount: integer Rupiah, hilangkan separator titik/koma, abaikan "Rp"/"IDR".
- status: "success" jika ada teks Berhasil/Sukses/Successful/Transaksi Berhasil.
  "pending" jika Diproses/Menunggu. "failed" jika Gagal/Ditolak. Else "unknown".
- timestamp: ISO 8601 jika bisa diparse, else string apa adanya dari struk.
- Jika field tidak terbaca jelas: kosongkan (string="" atau 0), JANGAN menebak."""


def analyze_payment_image(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    b64 = base64.b64encode(image_bytes).decode()
    resp = _get_client().chat.completions.create(
        model=VISION_MODEL,
        response_format={"type": "json_object"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
            ],
        }],
        temperature=0,
    )
    data = json.loads(resp.choices[0].message.content)
    return {
        "is_receipt": bool(data.get("is_receipt", False)),
        "status": str(data.get("status", "unknown")),
        "amount": int(data.get("amount", 0) or 0),
        "sender_name": str(data.get("sender_name", "")),
        "recipient_name": str(data.get("recipient_name", "")),
        "bank_or_app": str(data.get("bank_or_app", "")),
        "timestamp": str(data.get("timestamp", "")),
        "ref_no": str(data.get("ref_no", "")),
    }
