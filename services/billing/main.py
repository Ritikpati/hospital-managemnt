import os
from typing import Optional
from fastapi import Depends
from pydantic import BaseModel, Field
from common import *

app = base_app()
BUCKET = os.environ.get("RECEIPT_BUCKET", "")
DDL = """CREATE TABLE IF NOT EXISTS payments(
 id SERIAL PRIMARY KEY, patient_id INT NOT NULL, patient_name TEXT, patient_email TEXT,
 amount NUMERIC(12,2) NOT NULL CHECK (amount > 0), method TEXT, receipt_key TEXT,
 created_by TEXT, created_at TIMESTAMPTZ DEFAULT now());"""


@app.on_event("startup")
def start():
    init_db(DDL, ["payments"])


class Payment(BaseModel):
    patient_id: int
    patient_name: str
    patient_email: Optional[str] = None
    amount: float = Field(gt=0)
    method: str = "cash"


@app.post("/payments")
def pay(p: Payment, u=Depends(current_user)):
    row = write("INSERT INTO payments(patient_id,patient_name,patient_email,amount,method,created_by) "
                "VALUES(%s,%s,%s,%s,%s,%s) RETURNING id, created_at",
                (p.patient_id, p.patient_name, p.patient_email, p.amount, p.method, u["sub"]), fetch=True)[0]
    key = f"receipts/receipt-{row['id']}.txt"
    text = (f"HOSPITAL MANAGEMENT - PAYMENT RECEIPT\nReceipt #: {row['id']}\nDate: {row['created_at']:%Y-%m-%d %H:%M}\n"
            f"Patient: {p.patient_name} (ID {p.patient_id})\nAmount: {p.amount:.2f}\nMethod: {p.method}\n"
            f"Received by: {u['sub']}\n")
    put_bytes(BUCKET, key, text.encode(), "text/plain")
    write("UPDATE payments SET receipt_key=%s WHERE id=%s", (key, row["id"]))
    for to in {u["sub"], p.patient_email}:
        if to:
            notify(to, f"Payment receipt #{row['id']}", text)
    return {"id": row["id"], "receipt_url": presign(BUCKET, key)}


@app.get("/payments")
def payments(u=Depends(current_user)):
    if u["role"] == "admin":
        return read("SELECT * FROM payments ORDER BY id DESC")
    return read("SELECT * FROM payments WHERE created_by=%s ORDER BY id DESC", (u["sub"],))
