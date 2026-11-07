import os, uuid
from typing import List, Optional
import psycopg2.errors
from fastapi import Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from common import *

app = base_app()
PHOTOS = os.environ.get("PHOTO_BUCKET", "")
DDL = """
CREATE TABLE IF NOT EXISTS patients(
 id SERIAL PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL, address TEXT, city TEXT, state TEXT,
 age INT, mobile TEXT, email TEXT, gender TEXT, blood_group TEXT, occupation TEXT, heard_about_us TEXT,
 referred_by TEXT, diseases TEXT[] DEFAULT '{}', created_by TEXT, created_at TIMESTAMPTZ DEFAULT now());
CREATE TABLE IF NOT EXISTS weekly_records(
 id SERIAL PRIMARY KEY, patient_id INT REFERENCES patients(id), week INT CHECK (week BETWEEN 1 AND 5),
 symptoms TEXT, photo_key TEXT, created_by TEXT, created_at TIMESTAMPTZ DEFAULT now(), UNIQUE(patient_id, week));
CREATE TABLE IF NOT EXISTS tokens(
 id SERIAL PRIMARY KEY, patient_id INT REFERENCES patients(id), token_no INT NOT NULL, day DATE DEFAULT CURRENT_DATE,
 status TEXT DEFAULT 'waiting' CHECK (status IN ('waiting','in-progress','done')), UNIQUE(day, token_no));
"""


@app.on_event("startup")
def start():
    init_db(DDL, ["patients", "weekly_records", "tokens"])


class Patient(BaseModel):
    first_name: str
    last_name: str
    age: int
    mobile: str
    address: str = ""
    city: str = ""
    state: str = ""
    email: Optional[str] = None
    gender: str = ""
    blood_group: str = ""
    occupation: str = ""
    heard_about_us: str = ""
    referred_by: str = ""
    diseases: List[str] = []   # Jaundice, Hepatitis B, Fatty liver, Liver cirrhosis, Others


def with_photo(rows):
    for r in rows:
        r["photo_url"] = presign(PHOTOS, r["photo_key"]) if r.get("photo_key") else None
    return rows


@app.post("/patients")
def add_patient(p: Patient, u=Depends(current_user)):
    d = p.model_dump()
    cols = ",".join(d)
    row = write(f"INSERT INTO patients({cols},created_by) VALUES({','.join(['%s'] * len(d))},%s) RETURNING id",
                [*d.values(), u["sub"]], fetch=True)[0]
    if p.email:
        subscribe(p.email)
    return row


@app.get("/patients")
def list_patients(_=Depends(current_user)):
    return read("SELECT * FROM patients ORDER BY id DESC")


@app.get("/patients/weekly-report")
def report(_=Depends(current_user)):
    return with_photo(read("SELECT patient_id, week, symptoms, photo_key FROM weekly_records ORDER BY patient_id, week"))


@app.get("/patients/{pid}")
def get_patient(pid: int, _=Depends(current_user)):
    p = read("SELECT * FROM patients WHERE id=%s", (pid,))
    if not p:
        raise HTTPException(404, "Not found")
    return {**p[0], "weeks": with_photo(read("SELECT * FROM weekly_records WHERE patient_id=%s ORDER BY week", (pid,)))}


@app.post("/patients/{pid}/weeks")
async def add_week(pid: int, week: int = Form(...), symptoms: str = Form(""),
                   photo: Optional[UploadFile] = File(None), u=Depends(current_user)):
    key = f"patients/{pid}/week{week}-{uuid.uuid4().hex}.jpg" if photo and photo.filename else None
    try:
        write("INSERT INTO weekly_records(patient_id,week,symptoms,photo_key,created_by) VALUES(%s,%s,%s,%s,%s)",
              (pid, week, symptoms, key, u["sub"]))
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(409, "This week is already saved (saved data cannot be changed)")
    except psycopg2.errors.CheckViolation:
        raise HTTPException(400, "Week must be 1-5")
    if key:
        put_bytes(PHOTOS, key, await photo.read(), photo.content_type or "image/jpeg")
    return {"ok": True}


@app.post("/patients/{pid}/token")
def make_token_no(pid: int, _=Depends(current_user)):
    return write("INSERT INTO tokens(patient_id,token_no) SELECT %s, COALESCE(MAX(token_no),0)+1 "
                 "FROM tokens WHERE day=CURRENT_DATE RETURNING id, token_no", (pid,), fetch=True)[0]


@app.get("/queue")
def queue(_=Depends(current_user)):
    return read("SELECT t.id,t.token_no,t.status,p.first_name,p.last_name FROM tokens t "
                "JOIN patients p ON p.id=t.patient_id WHERE t.day=CURRENT_DATE ORDER BY t.token_no")


class Status(BaseModel):
    status: str


@app.patch("/queue/{tid}")
def set_status(tid: int, s: Status, _=Depends(current_user)):
    if s.status not in ("waiting", "in-progress", "done"):
        raise HTTPException(400, "Bad status")
    write("UPDATE tokens SET status=%s WHERE id=%s", (s.status, tid))
    return {"ok": True}
