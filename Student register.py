"""
student_register.py
Raspberry Pi + NFCリーダー + カメラ による学生証登録システム

フロー:
  Phase1: 学生証をリーダー+カメラにセット → OCRで学籍番号・氏名・顔写真を自動取得
  Phase2: OCR結果を確認 → YES/NO
          NOまたはOCR失敗 → 手動入力フォールバック
  Phase3: NFC (Type-F) からIDM取得 + 顔写真保存
  Phase4: 全データ紐づけ保存
  Phase5: 完了/失敗表示

依存: nfcpy, opencv-python, easyocr, pillow, tkinter(標準)
"""

import tkinter as tk
from tkinter import font as tkfont
import threading
import time
import json
import os
import re
import pickle
import datetime

import cv2
import numpy as np
from PIL import Image, ImageTk

# ── NFC ──────────────────────────────────
try:
    import nfc
    NFC_AVAILABLE = True
except ImportError:
    NFC_AVAILABLE = False
    print("[WARNING] nfcpy not found. NFC機能はダミー動作します。")

# ── OCR ──────────────────────────────────
try:
    import easyocr
    _ocr_reader = None  # 遅延初期化（初回起動コスト回避）
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("[WARNING] easyocr not found. OCR機能は無効。")


# ─────────────────────────────────────────
# 設定
# ─────────────────────────────────────────
DATA_DIR    = os.path.join(os.path.dirname(__file__), "data")
FACE_DIR    = os.path.join(DATA_DIR, "faces")
RECORD_FILE = os.path.join(DATA_DIR, "records.pkl")
CAMERA_INDEX = 0
NFC_DEVICE   = "usb"   # e.g. "tty:S0:pn532"

# 学籍番号パターン（英字1〜4文字 + 数字4〜10文字、または純英数字6〜14文字）
# 学校仕様に合わせて調整
STUDENT_ID_PATTERN = re.compile(r'^[A-Za-z]{1,4}[0-9]{4,10}$|^[A-Za-z0-9]{6,14}$')

# NFCブロック・システムコード
FELICA_SYSTEM_CODE = 0x88B4
BLOCK_IDM          = 131

os.makedirs(FACE_DIR, exist_ok=True)


# ─────────────────────────────────────────
# OCRユーティリティ
# ─────────────────────────────────────────
def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        _ocr_reader = easyocr.Reader(["ja", "en"], gpu=False)
    return _ocr_reader


def ocr_scan_card(frame: np.ndarray) -> dict:
    """
    学生証画像からOCRで情報を抽出する。
    戻り値:
        {
            "student_id": str | None,   # 学籍番号候補
            "name":       str | None,   # 氏名候補（日本語テキスト）
            "face_roi":   np.ndarray | None,  # 顔写真領域（切り抜き）
            "all_texts":  list[str],    # 全検出テキスト
        }
    """
    result = {"student_id": None, "name": None, "face_roi": None, "all_texts": []}

    if not OCR_AVAILABLE:
        return result

    reader = _get_ocr_reader()
    detections = reader.readtext(frame)  # [(bbox, text, conf), ...]

    all_texts = []
    student_id_candidates = []
    name_candidates = []

    for bbox, text, conf in detections:
        cleaned = text.strip()
        if not cleaned:
            continue
        all_texts.append(cleaned)

        # 学籍番号候補: 英数字のみ、パターンに一致、信頼度0.5以上
        no_space = cleaned.replace(" ", "").replace("-", "").replace("　", "")
        if conf >= 0.5 and STUDENT_ID_PATTERN.match(no_space):
            student_id_candidates.append((conf, no_space))

        # 氏名候補: 日本語（ひらがな・カタカナ・漢字）を含む、2文字以上、信頼度0.5以上
        has_jp = bool(re.search(r'[\u3040-\u9fff]', cleaned))
        if has_jp and conf >= 0.5 and 2 <= len(cleaned.replace(" ", "")) <= 20:
            name_candidates.append((conf, cleaned))

    result["all_texts"] = all_texts

    # 信頼度最高のものを採用
    if student_id_candidates:
        result["student_id"] = max(student_id_candidates, key=lambda x: x[0])[1].upper()
    if name_candidates:
        result["name"] = max(name_candidates, key=lambda x: x[0])[1]

    # 顔写真領域: Haar cascadeで顔検出して切り抜き
    result["face_roi"] = _detect_face_roi(frame)

    return result


def _detect_face_roi(frame: np.ndarray) -> np.ndarray | None:
    """学生証上の顔写真領域を検出して返す。"""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    cascade = cv2.CascadeClassifier(cascade_path)
    faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
    if len(faces) == 0:
        return None
    # 最大面積の顔を選ぶ
    x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
    margin = int(min(w, h) * 0.15)
    x1 = max(0, x - margin)
    y1 = max(0, y - margin)
    x2 = min(frame.shape[1], x + w + margin)
    y2 = min(frame.shape[0], y + h + margin)
    return frame[y1:y2, x1:x2]


# ─────────────────────────────────────────
# カメラユーティリティ
# ─────────────────────────────────────────
def get_camera_frame() -> np.ndarray | None:
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        return None
    # 安定するまで数フレーム読み捨て
    for _ in range(3):
        cap.read()
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def save_face_image(student_id: str, face_roi: np.ndarray | None, full_frame: np.ndarray | None) -> str:
    """顔ROIまたはフルフレームを保存してパスを返す。"""
    path = os.path.join(FACE_DIR, f"{student_id}.jpg")
    img = face_roi if face_roi is not None else full_frame
    if img is not None:
        cv2.imwrite(path, img)
        return path
    return ""


# ─────────────────────────────────────────
# NFC読み取り (Type-F / Felica専用)
# ─────────────────────────────────────────
def read_nfc_blocking(timeout: int = 60) -> dict | None:
    """
    戻り値:
        {
            "idm":       "012E50E6E84C625D",
            "idm_bytes": b'\x01\x2e...',
            "pmm":       "00F100000001​4300",
        }
    失敗/タイムアウト時は None。
    """
    if not NFC_AVAILABLE:
        time.sleep(1)
        idm_bytes = bytes([0x01, 0x2e, 0x50, 0xe6, 0xe8, 0x4c, 0x62, 0x5d])
        pmm_bytes = bytes([0x00, 0xf1, 0x00, 0x00, 0x00, 0x01, 0x43, 0x00])
        return {
            "idm":       idm_bytes.hex().upper(),
            "idm_bytes": idm_bytes,
            "pmm":       pmm_bytes.hex().upper(),
        }

    result = {}
    start  = time.time()

    def on_connect(tag):
        if not isinstance(tag, nfc.tag.tt3.Type3Tag):
            return False
        idm_raw = bytes(tag.identifier)
        try:
            sc   = nfc.tag.tt3.ServiceCode(0x000B, 0x0B)
            bc   = nfc.tag.tt3.BlockCode(BLOCK_IDM, service=0)
            data = tag.read_without_encryption([sc], [bc])
            blk  = bytes(data[0]) if data else None
        except Exception:
            blk = None

        if blk and len(blk) >= 16:
            idm_bytes = blk[0:8]
            pmm_bytes = blk[8:16]
        else:
            idm_bytes = idm_raw
            pmm_bytes = b'\x00' * 8

        result["idm"]       = idm_bytes.hex().upper()
        result["idm_bytes"] = idm_bytes
        result["pmm"]       = pmm_bytes.hex().upper()
        return True

    clf = nfc.ContactlessFrontend()
    try:
        clf.open(NFC_DEVICE)
        clf.connect(
            rdwr={"on-connect": on_connect, "targets": ["212F"]},
            terminate=lambda: bool(result) or (time.time() > start + timeout),
        )
    finally:
        clf.close()

    return result if result else None


# ─────────────────────────────────────────
# データ保存
# ─────────────────────────────────────────
def load_records() -> dict:
    if os.path.exists(RECORD_FILE):
        with open(RECORD_FILE, "rb") as f:
            return pickle.load(f)
    return {}


def save_record(student_id: str, name: str, nfc_data: dict, face_path: str):
    records = load_records()
    idm_bytes = nfc_data.get("idm_bytes", b"")
    records[student_id] = {
        "student_id":      student_id,
        "name":            name,
        "idm":             nfc_data.get("idm", ""),
        "idm_bytes":       idm_bytes,
        "pmm":             nfc_data.get("pmm", ""),
        "face_image_path": face_path,
        "registered_at":   datetime.datetime.now().isoformat(),
        # TODO: 暗号化 + サーバーアップロード
    }
    with open(RECORD_FILE, "wb") as f:
        pickle.dump(records, f)
    # JSON（可読用）
    json_path = RECORD_FILE.replace(".pkl", ".json")
    json_records = {}
    for k, v in records.items():
        row = dict(v)
        row["idm_bytes"] = row["idm_bytes"].hex().upper() if row["idm_bytes"] else ""
        json_records[k] = row
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_records, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────
# GUI
# ─────────────────────────────────────────
BG    = "#0a0a14"
FG    = "#e8e8f0"
BLUE  = "#1e90ff"
GREEN = "#28a745"
RED   = "#cc3333"
GOLD  = "#ffcc00"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("学生証登録システム")
        self.attributes("-fullscreen", True)
        self.configure(bg=BG)

        self._fl = tkfont.Font(family="Noto Sans CJK JP", size=28, weight="bold")
        self._fm = tkfont.Font(family="Noto Sans CJK JP", size=18)
        self._fs = tkfont.Font(family="Noto Sans CJK JP", size=13)

        # 登録セッション変数
        self.student_id  = tk.StringVar()
        self.student_name = tk.StringVar()
        self._nfc_data   = None
        self._face_roi   = None
        self._full_frame = None
        self._face_path  = ""
        self._nfc_thread = None

        self._container = tk.Frame(self, bg=BG)
        self._container.pack(fill="both", expand=True)

        self.show_phase1_scan()

    # ── ウィジェットヘルパー ────────────
    def _clear(self):
        for w in self._container.winfo_children():
            w.destroy()

    def _lbl(self, parent, text, f=None, fg=FG, **kw):
        f = f or self._fm
        return tk.Label(parent, text=text, font=f, fg=fg, bg=BG, **kw)

    def _btn(self, parent, text, cmd, bg=BLUE, **kw):
        return tk.Button(
            parent, text=text, command=cmd, font=self._fm,
            bg=bg, fg="white", activebackground="#004eaa",
            relief="flat", padx=20, pady=10, cursor="hand2", **kw
        )

    def _soft_kb(self, parent, var: tk.StringVar):
        """ソフトキーボード（フォールバック用）"""
        rows = ["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
        for row in rows:
            r = tk.Frame(parent, bg=BG)
            r.pack()
            for ch in row:
                tk.Button(
                    r, text=ch, width=3, font=self._fm,
                    bg="#1e1e2e", fg=FG, activebackground="#2e2e4e",
                    relief="flat",
                    command=lambda c=ch: var.set(var.get() + c)
                ).pack(side="left", padx=2, pady=2)
        tk.Button(
            parent, text="⌫", width=6, font=self._fm,
            bg="#3a1e1e", fg=FG, relief="flat",
            command=lambda: var.set(var.get()[:-1])
        ).pack(pady=4)

    # ═══════════════════════════════════
    # Phase 1A: OCRスキャン
    # ═══════════════════════════════════
    def show_phase1_scan(self):
        """学生証をカメラにかざす → OCR自動スキャン"""
        self._clear()
        self.student_id.set("")
        self.student_name.set("")
        self._nfc_data   = None
        self._face_roi   = None
        self._full_frame = None
        f = self._container

        self._lbl(f, "学生証登録システム", self._fl).pack(pady=(40, 4))
        self._lbl(f, "学生証をカメラの前にかざしてください", fg="#aaa").pack(pady=(0, 16))

        # カメラプレビュー
        self._preview = tk.Label(f, bg=BG)
        self._preview.pack()

        self._status_var = tk.StringVar(value="スキャン待機中...")
        self._lbl(f, "", fg=GOLD, textvariable=self._status_var).pack(pady=8)

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack(pady=8)
        self._btn(btn_row, "📷  今すぐスキャン", self._do_ocr_scan, bg=GREEN).pack(side="left", padx=8)
        self._btn(btn_row, "手動入力", self.show_phase1_manual, bg="#555").pack(side="left", padx=8)

        self._btn(f, "終了", self.destroy, bg="#333").pack(pady=6)

        # プレビュー自動更新
        self._scanning = True
        self._update_preview_loop()

    def _update_preview_loop(self):
        if not self._scanning:
            return
        frame = get_camera_frame()
        if frame is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb).resize((400, 300))
            imgtk = ImageTk.PhotoImage(image=img)
            self._preview.imgtk = imgtk
            self._preview.configure(image=imgtk)
        self.after(150, self._update_preview_loop)

    def _do_ocr_scan(self):
        self._status_var.set("スキャン中...")
        self._scanning = False

        def run():
            frame = get_camera_frame()
            if frame is None:
                self.after(0, lambda: self._ocr_fallback("カメラが使えません"))
                return
            self._full_frame = frame
            ocr_result = ocr_scan_card(frame)
            self.after(0, self._on_ocr_done, ocr_result, frame)

        threading.Thread(target=run, daemon=True).start()

    def _on_ocr_done(self, ocr_result: dict, frame: np.ndarray):
        sid  = ocr_result.get("student_id")
        name = ocr_result.get("name")
        roi  = ocr_result.get("face_roi")

        if not sid:
            self._ocr_fallback("学籍番号を検出できませんでした。手動で入力してください。")
            return

        self._face_roi = roi
        self.show_phase1_confirm(sid, name, frame, roi)

    def _ocr_fallback(self, msg: str):
        self._scanning = False
        self.show_phase1_manual(error=msg)

    # ═══════════════════════════════════
    # Phase 1B: OCR確認
    # ═══════════════════════════════════
    def show_phase1_confirm(self, sid: str, name: str | None, frame: np.ndarray, face_roi: np.ndarray | None):
        """OCR結果を表示 → ユーザーが確認"""
        self._clear()
        f = self._container

        self._lbl(f, "スキャン結果の確認", self._fl).pack(pady=(40, 16))

        info_frame = tk.Frame(f, bg="#1a1a28", padx=30, pady=20)
        info_frame.pack(pady=8)

        self._lbl(info_frame, f"学籍番号:  {sid}", fg="#7ddfff").pack(anchor="w", pady=4)
        self._lbl(info_frame, f"氏　　名:  {name or '（検出できませんでした）'}", fg="#aaffaa").pack(anchor="w", pady=4)

        # 顔写真プレビュー
        preview_img = face_roi if face_roi is not None else frame
        if preview_img is not None:
            rgb   = cv2.cvtColor(preview_img, cv2.COLOR_BGR2RGB)
            h, w  = rgb.shape[:2]
            scale = min(160 / w, 160 / h)
            img   = Image.fromarray(rgb).resize((int(w * scale), int(h * scale)))
            imgtk = ImageTk.PhotoImage(image=img)
            lbl   = tk.Label(info_frame, image=imgtk, bg="#1a1a28")
            lbl.imgtk = imgtk
            lbl.pack(pady=8)

        self._lbl(f, "この内容で登録しますか？").pack(pady=12)

        btn_row = tk.Frame(f, bg=BG)
        btn_row.pack()

        def on_yes():
            self.student_id.set(sid)
            self.student_name.set(name or "")
            self._face_roi = face_roi
            self.show_phase2_nfc()

        self._btn(btn_row, "✅  はい、NFCを読み取る", on_yes, bg=GREEN).pack(side="left", padx=12)
        self._btn(btn_row, "❌  やり直す", self.show_phase1_scan, bg=RED).pack(side="left", padx=12)
        self._btn(btn_row, "手動入力に切替", self.show_phase1_manual, bg="#555").pack(side="left", padx=12)

    # ═══════════════════════════════════
    # Phase 1C: 手動入力フォールバック
    # ═══════════════════════════════════
    def show_phase1_manual(self, error: str = ""):
        self._clear()
        self._scanning = False
        f = self._container

        self._lbl(f, "手動入力", self._fl).pack(pady=(40, 8))
        if error:
            self._lbl(f, error, fg="#ff8888", f=self._fs).pack(pady=(0, 8))

        self._lbl(f, "学籍番号").pack()
        id_entry = tk.Entry(
            f, textvariable=self.student_id,
            font=self._fl, bg="#1e1e2e", fg=FG,
            insertbackground="white", relief="flat", width=18, justify="center"
        )
        id_entry.pack(pady=6)
        id_entry.focus_set()

        self._lbl(f, "氏名（任意）").pack(pady=(10, 0))
        tk.Entry(
            f, textvariable=self.student_name,
            font=self._fm, bg="#1e1e2e", fg=FG,
            insertbackground="white", relief="flat", width=24, justify="center"
        ).pack(pady=6)

        kb = tk.Frame(f, bg=BG)
        kb.pack(pady=6)
        self._soft_kb(kb, self.student_id)

        self._err_var = tk.StringVar()
        self._lbl(f, "", fg="#ff4444", textvariable=self._err_var, f=self._fs).pack(pady=2)

        def on_next():
            sid = self.student_id.get().strip().upper()
            if not sid or len(sid) < 4:
                self._err_var.set("学籍番号が短すぎます")
                return
            self.student_id.set(sid)
            self.show_phase2_nfc()

        self._btn(f, "次へ → NFCを読み取る", on_next, bg=GREEN).pack(pady=10)
        self._btn(f, "← スキャンに戻る", self.show_phase1_scan, bg="#555").pack(pady=4)

    # ═══════════════════════════════════
    # Phase 2: NFC読み取り
    # ═══════════════════════════════════
    def show_phase2_nfc(self):
        self._clear()
        f = self._container

        self._lbl(f, "NFC 読み取り", self._fl).pack(pady=(50, 12))
        self._lbl(f, f"学籍番号: {self.student_id.get()}", fg=BLUE).pack()
        if self.student_name.get():
            self._lbl(f, f"氏名: {self.student_name.get()}", fg="#aaffaa").pack()
        self._lbl(f, "学生証をリーダーの上に置いてください").pack(pady=16)

        self._spin_var = tk.StringVar(value="待機中...")
        self._lbl(f, "", fg=GOLD, textvariable=self._spin_var).pack(pady=6)

        # NFC読み取り開始
        self._nfc_data = None
        self._dot      = 0
        self._nfc_thread = threading.Thread(target=self._nfc_worker, daemon=True)
        self._nfc_thread.start()
        self._spin_loop()

    def _spin_loop(self):
        if self._nfc_data is not None or (self._nfc_thread and not self._nfc_thread.is_alive()):
            return
        self._dot = (self._dot + 1) % 4
        self._spin_var.set("NFC読み取り中" + "." * self._dot)
        self.after(250, self._spin_loop)

    def _nfc_worker(self):
        try:
            data = read_nfc_blocking(timeout=60)
        except Exception as e:
            print(f"[NFC ERROR] {e}")
            data = None
        self.after(0, self._on_nfc_done, data)

    def _on_nfc_done(self, data):
        if not data:
            self.show_phase5(success=False, error="NFCの読み取りに失敗しました")
            return
        self._nfc_data = data
        self.show_phase3_save()

    # ═══════════════════════════════════
    # Phase 3: 保存
    # ═══════════════════════════════════
    def show_phase3_save(self):
        self._clear()
        f = self._container
        self._lbl(f, "データ保存中...", self._fl).pack(pady=(100, 20))

        def run():
            try:
                sid  = self.student_id.get().strip().upper()
                name = self.student_name.get().strip()
                path = save_face_image(sid, self._face_roi, self._full_frame)
                save_record(sid, name, self._nfc_data, path)
                self._face_path = path
                self.after(600, lambda: self.show_phase5(success=True))
            except Exception as e:
                self.after(0, lambda: self.show_phase5(success=False, error=str(e)))

        threading.Thread(target=run, daemon=True).start()

    # ═══════════════════════════════════
    # Phase 5: 完了/失敗
    # ═══════════════════════════════════
    def show_phase5(self, success: bool, error: str = ""):
        self._clear()
        f = self._container

        if success:
            idm = self._nfc_data.get("idm", "N/A") if self._nfc_data else "N/A"
            self._lbl(f, "✅  登録完了", self._fl, fg="#28a745").pack(pady=(70, 16))

            info = tk.Frame(f, bg="#0f1f0f", padx=24, pady=16)
            info.pack(pady=8)
            self._lbl(info, f"学籍番号: {self.student_id.get()}",        fg="#7ddfff").pack(anchor="w", pady=3)
            self._lbl(info, f"氏　　名: {self.student_name.get() or '—'}", fg="#aaffaa").pack(anchor="w", pady=3)
            self._lbl(info, f"IDM     : {idm}",                           fg="#cccccc", f=self._fs).pack(anchor="w", pady=3)

            self._lbl(f, "学生証をリーダーから取り外してください", fg=GOLD).pack(pady=20)
            self._btn(f, "次の登録へ", self.show_phase1_scan, bg=GREEN).pack(pady=8)
        else:
            self._lbl(f, "❌  登録失敗", self._fl, fg=RED).pack(pady=(70, 16))
            self._lbl(f, f"エラー: {error}", fg="#ff8888", f=self._fs).pack(pady=8)
            self._lbl(f, "最初からやり直してください").pack(pady=8)
            self._btn(f, "最初からやり直す", self.show_phase1_scan, bg=RED).pack(pady=10)

        self._btn(f, "終了", self.destroy, bg="#333").pack(pady=6)


# ─────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()