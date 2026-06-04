"""Test seluruh fitur C2C.

Mock Groq (deterministik, no network) untuk semua endpoint + DB + keyword gate.
Live Groq smoke test opsional: jalankan dgn  RUN_LIVE=1 pytest -k live
"""
import json
import os
import tempfile

# DB_DIR + key HARUS di-set sebelum import app (db.py baca DB_DIR saat import)
_TMP = tempfile.mkdtemp(prefix="c2c_test_")
os.environ["DB_DIR"] = _TMP
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ["VERIFY_TOKEN"] = "c2c_verify"

import pytest
from fastapi.testclient import TestClient

import app.main as main
import app.services.ai_service as ai
from app import db
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _init_db():
    db.init_db()
    yield


# ----- fake Groq client (utk test analyze_conversation gate langsung) -----
class _FakeClient:
    def __init__(self, content):
        self._content = content
        self.chat = self
        self.completions = self

    def create(self, *a, **k):
        msg = type("M", (), {"content": self._content})
        choice = type("C", (), {"message": msg})
        return type("R", (), {"choices": [choice]})


def _fake_groq(monkeypatch, payload: dict):
    monkeypatch.setattr(ai, "_get_client", lambda: _FakeClient(json.dumps(payload)))


# ============================ HEALTH / STATIC ============================
def test_health():
    r = client.get("/")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_dashboard():
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert "<" in r.text and len(r.text) > 100


# ============================ WEBHOOK VERIFY ============================
def test_webhook_verify_ok():
    r = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "c2c_verify", "hub.challenge": "42"})
    assert r.status_code == 200 and r.text == "42"


def test_webhook_verify_fail():
    r = client.get("/webhook", params={
        "hub.mode": "subscribe", "hub.verify_token": "salah", "hub.challenge": "42"})
    assert r.status_code == 403


# ============================ WEBHOOK POST ============================
def _wh_text(body, frm="6280001"):
    return {"entry": [{"changes": [{"value": {"messages": [
        {"from": frm, "type": "text", "text": {"body": body}}]}}]}]}


def test_webhook_text_income(monkeypatch):
    monkeypatch.setattr(main, "analyze_message", lambda t: {
        "intent": "income", "amount": 500000, "category": "sales", "description": "kue"})
    r = client.post("/webhook", json=_wh_text("terima 500rb", "628111"))
    assert r.status_code == 200
    assert "Pemasukan" in r.json()["reply"]
    assert any(t["amount"] == 500000 for t in db.get_transactions("628111"))


def test_webhook_text_unknown_no_insert(monkeypatch):
    monkeypatch.setattr(main, "analyze_message", lambda t: {
        "intent": "unknown", "amount": 0, "category": "", "description": ""})
    r = client.post("/webhook", json=_wh_text("halo", "628112"))
    assert r.status_code == 200
    assert "Tidak dapat" in r.json()["reply"]
    assert db.get_transactions("628112") == []


def test_webhook_audio(monkeypatch):
    monkeypatch.setattr(main, "transcribe_audio", lambda url: "habis 20rb makan")
    monkeypatch.setattr(main, "analyze_message", lambda t: {
        "intent": "expense", "amount": 20000, "category": "food", "description": "makan"})
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "628113", "type": "audio", "audio": {"id": "AUDIO_ID"}}]}}]}]}
    r = client.post("/webhook", json=body)
    assert r.status_code == 200
    assert "Transkripsi" in r.json()["reply"] and "Pengeluaran" in r.json()["reply"]


def test_webhook_image_type():
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "628114", "type": "image", "image": {"id": "x"}}]}}]}]}
    r = client.post("/webhook", json=body)
    assert r.status_code == 200 and "dashboard" in r.json()["reply"].lower()


def test_webhook_unsupported():
    body = {"entry": [{"changes": [{"value": {"messages": [
        {"from": "628115", "type": "sticker"}]}}]}]}
    r = client.post("/webhook", json=body)
    assert r.status_code == 200 and "belum didukung" in r.json()["reply"]


def test_webhook_malformed():
    r = client.post("/webhook", json={"foo": "bar"})
    assert r.status_code == 200 and r.json()["status"] == "ignored"


# ============================ /send ============================
def test_send(monkeypatch):
    monkeypatch.setattr(main, "analyze_message", lambda t: {
        "intent": "expense", "amount": 20000, "category": "food", "description": "makan siang"})
    r = client.post("/send", json={"phone_number": "628120", "message": "habis 20rb"})
    assert r.status_code == 200 and "Pengeluaran" in r.json()["reply"]
    assert db.get_transactions("628120")[0]["amount"] == 20000


# ============================ /send-audio ============================
def test_send_audio(monkeypatch):
    monkeypatch.setattr(main, "transcribe_audio_bytes", lambda b, m: "dapat 100rb")
    monkeypatch.setattr(main, "analyze_message", lambda t: {
        "intent": "income", "amount": 100000, "category": "sales", "description": "jual"})
    import base64
    payload = {"phone_number": "628121", "audio_b64": base64.b64encode(b"x").decode(),
               "mime_type": "audio/webm"}
    r = client.post("/send-audio", json=payload)
    assert r.status_code == 200
    assert r.json()["transcript"] == "dapat 100rb"
    assert "Pemasukan" in r.json()["reply"]


# ============================ /send-image ============================
def _img_payload(phone):
    import base64
    return {"phone_number": phone, "image_b64": base64.b64encode(b"img").decode(),
            "mime_type": "image/jpeg"}


def test_send_image_success(monkeypatch):
    monkeypatch.setattr(main, "analyze_payment_image", lambda b, m: {
        "is_receipt": True, "status": "success", "amount": 250000,
        "sender_name": "Budi", "recipient_name": "Siti", "bank_or_app": "BCA",
        "timestamp": "", "ref_no": "REF1"})
    r = client.post("/send-image", json=_img_payload("628130"))
    assert r.status_code == 200 and "terverifikasi" in r.json()["reply"]
    assert db.get_transactions("628130")[0]["amount"] == 250000


def test_send_image_not_receipt(monkeypatch):
    monkeypatch.setattr(main, "analyze_payment_image", lambda b, m: {
        "is_receipt": False, "status": "unknown", "amount": 0, "sender_name": "",
        "recipient_name": "", "bank_or_app": "", "timestamp": "", "ref_no": ""})
    r = client.post("/send-image", json=_img_payload("628131"))
    assert r.status_code == 200 and "bukan bukti" in r.json()["reply"].lower()
    assert db.get_transactions("628131") == []


def test_send_image_pending(monkeypatch):
    monkeypatch.setattr(main, "analyze_payment_image", lambda b, m: {
        "is_receipt": True, "status": "pending", "amount": 50000, "sender_name": "",
        "recipient_name": "", "bank_or_app": "", "timestamp": "", "ref_no": ""})
    r = client.post("/send-image", json=_img_payload("628132"))
    assert r.status_code == 200 and "pending" in r.json()["reply"]
    assert db.get_transactions("628132") == []


# ============================ /conversation ============================
def test_conversation_record(monkeypatch):
    monkeypatch.setattr(main, "analyze_conversation", lambda h, r: {
        "action": "record", "intent": "income", "amount": 150000,
        "category": "sales", "description": "kue tart", "reply": "tercatat"})
    payload = {"phone_number": "628140", "history": [
        {"role": "lawan", "content": "udah transfer 150rb"}], "recorded_txns": []}
    r = client.post("/conversation", json=payload)
    j = r.json()
    assert r.status_code == 200 and j["recorded_id"] is not None
    assert j["transaction"]["amount"] == 150000


def test_conversation_skip(monkeypatch):
    monkeypatch.setattr(main, "analyze_conversation", lambda h, r: {
        "action": "skip", "intent": None, "amount": 0,
        "category": "", "description": "", "reply": "ada yg bisa dibantu?"})
    payload = {"phone_number": "628141", "history": [
        {"role": "lawan", "content": "harga kue berapa?"}], "recorded_txns": []}
    r = client.post("/conversation", json=payload)
    j = r.json()
    assert r.status_code == 200 and j["recorded_id"] is None and j["transaction"] is None


# ============================ transactions / report ============================
def test_transactions_list():
    db.insert_transaction("628150", "income", 1000, "sales", "a")
    db.insert_transaction("628150", "expense", 500, "food", "b")
    r = client.get("/transactions/628150")
    assert r.status_code == 200 and len(r.json()["transactions"]) == 2


def test_report_pdf():
    db.insert_transaction("628160", "income", 300000, "sales", "jual kue")
    db.insert_transaction("628160", "expense", 100000, "supplies", "beli tepung")
    r = client.get("/report/628160")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:4] == b"%PDF"


def test_report_pdf_empty():
    r = client.get("/report/628199")
    assert r.status_code == 200 and r.content[:4] == b"%PDF"


# ============================ DB unit ============================
def test_db_insert_returns_id():
    i1 = db.insert_transaction("628170", "income", 10, "x", "y")
    i2 = db.insert_transaction("628170", "income", 20, "x", "y")
    assert isinstance(i1, int) and i2 > i1


def test_db_filter_by_phone():
    db.insert_transaction("628180", "income", 1, "x", "y")
    db.insert_transaction("628181", "income", 2, "x", "y")
    assert all(t["phone_number"] == "628180" for t in db.get_transactions("628180"))


# ============================ KEYWORD GATE (logika kritis) ============================
def test_gate_record_with_keyword(monkeypatch):
    _fake_groq(monkeypatch, {"action": "record", "intent": "income", "amount": 100000,
                             "category": "sales", "description": "kue"})
    out = ai.analyze_conversation([{"role": "lawan", "content": "udah transfer ya"}], [])
    assert out["action"] == "record" and out["intent"] == "income" and out["amount"] == 100000


def test_gate_forced_skip_no_keyword(monkeypatch):
    # LLM bilang record, tapi pesan terakhir tdk ada kata-kunci bayar -> WAJIB skip
    _fake_groq(monkeypatch, {"action": "record", "intent": "income", "amount": 100000,
                             "category": "sales", "description": "kue"})
    out = ai.analyze_conversation([{"role": "lawan", "content": "halo kak mau pesan"}], [])
    assert out["action"] == "skip"


def test_gate_expense_when_seller_pays(monkeypatch):
    _fake_groq(monkeypatch, {"action": "record", "intent": "income", "amount": 80000,
                             "category": "supplies", "description": "beli bahan"})
    out = ai.analyze_conversation([{"role": "saya", "content": "udah saya bayar lunas"}], [])
    assert out["action"] == "record" and out["intent"] == "expense"


# ============================ LIVE GROQ (opsional) ============================
@pytest.mark.skipif(os.getenv("RUN_LIVE") != "1", reason="set RUN_LIVE=1 untuk test Groq asli")
def test_live_groq_analyze_message():
    from dotenv import load_dotenv
    load_dotenv(override=True)        # pakai GROQ_API_KEY asli dari .env
    ai._client = None                 # reset cache lazy-init
    res = ai.analyze_message("habis 20rb buat makan siang")
    assert res["intent"] == "expense" and res["amount"] == 20000
