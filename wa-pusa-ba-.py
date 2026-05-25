from fastapi import FastAPI, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import sqlite3
from datetime import datetime
import face_recognition
import numpy as np
import cv2
import json

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- データベースの初期化 ---
def init_db():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    # 学生データ（顔の特徴量データ face_encoding も保存）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            tag_id TEXT PRIMARY KEY,
            student_id TEXT,
            name TEXT,
            face_encoding TEXT
        )
    """)
    # 入退室・認証履歴
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT,
            status TEXT,
            message TEXT,
            timestamp TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

# --- クライアントからデータを受信・照合するAPI ---
@app.post("/api/scan")
async def scan_card(raw_data: str = Form(...), face_image: UploadFile = File(...)):
    # 1. データの分解（学籍番号とタグIDの抽出）
    try:
        parts = raw_data.split(":")
        scanned_student_id = parts[0] # "2323091"
        tag_id = parts[1].split(",")[0] # "012E50E6E84CC053"
    except Exception:
        return {"status": "ERROR", "message": "データ形式が不正です"}

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    
    # 2. タグIDが登録されているか確認
    cursor.execute("SELECT student_id, name, face_encoding FROM students WHERE tag_id = ?", (tag_id,))
    student = cursor.fetchone()

    status = ""
    message = ""
    
    if not student:
        # 未登録のタグだった場合（かざして新規登録用）
        status = "UNKNOWN_TAG"
        message = f"未登録のタグです (学籍番号候補: {scanned_student_id})"
        cursor.execute("INSERT INTO logs (student_id, status, message, timestamp) VALUES (?, ?, ?, ?)",
                       (scanned_student_id, status, message, timestamp))
    else:
        db_student_id, name, db_face_encoding_str = student
        
        # 3. 顔認証処理
        image_bytes = await face_image.read()
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        # 写真から顔の特徴を抽出
        face_locations = face_recognition.face_locations(img)
        
        if len(face_locations) == 0:
            status = "NO_FACE"
            message = "顔が検出されませんでした"
        else:
            uploaded_encoding = face_recognition.face_encodings(img, face_locations)[0]
            
            # DBに保存されている顔データ(JSON文字列)を配列に戻す
            known_encoding = np.array(json.loads(db_face_encoding_str))
            
            # 顔の比較 (True / False)
            match = face_recognition.compare_faces([known_encoding], uploaded_encoding)[0]
            
            if match:
                status = "ALLOWED"
                message = f"認証成功: {name} さん"
            else:
                status = "DENIED"
                message = f"顔が一致しません (本人拒否/なりすまし)"
                
        # 履歴の保存
        cursor.execute("INSERT INTO logs (student_id, status, message, timestamp) VALUES (?, ?, ?, ?)",
                       (db_student_id, status, message, timestamp))

    conn.commit()
    conn.close()
    
    return {"status": status, "message": message, "tag_id": tag_id}

# --- 照合結果を確認するWeb画面 ---
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT student_id, status, message, timestamp FROM logs ORDER BY id DESC LIMIT 15")
    logs = cursor.fetchall()
    conn.close()
    
    return templates.TemplateResponse("index.html", {"request": request, "logs": logs})