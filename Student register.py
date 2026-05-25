"""
student_register.py
Raspberry Pi + NFCリーダー + カメラ による学生証登録システム
依存: nfcpy, opencv-python, easyocr, pillow, tkinter(標準)
"""

import tkinter as tk
from tkinter import font as tkfont
import threading
import time
import json
import os
import pickle
import datetime
import traceback

import cv2
import numpy as np
from PIL import Image, ImageTk

# NFC
try:
    import nfc
    NFC_AVAILABLE = True
except ImportError:
    NFC_AVAILABLE = False
    print("[WARNING] nfcpy not found. NFC機能はダミー動作します。")

# OCR（任意）
try:
    import easyocr
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    print("[WARNING] easyocr not found. OCR機能は無効。")


# ─────────────────────────────────────────
# 設定
# ─────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
FACE_DIR = os.path.join(DATA_DIR, "faces")
RECORD_FILE = os.path.join(DATA_DIR, "records.pkl")
CAMERA_INDEX = 0
NFC_DEVICE = "usb"  # 環境に合わせて変更 e.g. "tty:S0:pn532"

os.makedirs(FACE_DIR, exist_ok=True)


# ─────────────────────────────────────────
# データ保存
# ─────────────────────────────────────────
def load_records() -> dict:
    if os.path.exists(RECORD_FILE):
        with open(RECORD_FILE, "rb") as f:
            return pickle.load(f)
    return {}


def save_record(student_id: str, nfc_data: dict, face_path: str):
    records = load_records()
    idm_bytes = nfc_data.get("idm_bytes", b"")
    records[student_id] = {
        "student_id":      student_id,
        # IDM: 8バイト = 16文字 hex (Block131 先頭8バイト)
        "idm":             nfc_data.get("idm", ""),
        "idm_bytes":       idm_bytes,          # bytes型: pickle用
        # PMM: 8バイト
        "pmm":             nfc_data.get("pmm", ""),
        "face_image_path": face_path,
        "registered_at":   datetime.datetime.now().isoformat(),
        # TODO: 暗号化後サーバーアップロード
    }
    with open(RECORD_FILE, "wb") as f:
        pickle.dump(records, f)
    # JSON出力（可読用・bytes は hex文字列に変換）
    json_path = RECORD_FILE.replace(".pkl", ".json")
    json_records = {}
    for k, v in records.items():
        row = dict(v)
        row["idm_bytes"] = row["idm_bytes"].hex().upper() if row["idm_bytes"] else ""
        json_records[k] = row
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_records, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────
# NFC読み取り (Type-F / Felica専用)
# ─────────────────────────────────────────
#
# ブロック構成（テストデータより）:
#   Block 130: IDD[8], DFC[2], ...
#   Block 131: IDM[8], PMM[8]  ← 先頭8バイトがIDM
#   Block 132: SERVICE_CODE[2], ...
#   Block 133: SYSTEM_CODE[2] = 88 B4, ...
#
# 取得対象: Block 131 の先頭8バイト (IDM)
# サービスコード: Block 132 の先頭2バイト = 00 00 → 0x0000
# システムコード: 0x88B4 (テストデータBlock133より)
#
# nfcpy Read Without Encryption コマンド仕様:
#   ServiceCode はリトルエンディアン。
#   ブロック番号はスクラッチパッドの絶対番号。
# ─────────────────────────────────────────

# システムコード 0x88B4 のFelicaに限定してポーリング
FELICA_SYSTEM_CODE = 0x88B4

# IDMが格納されているブロック番号
BLOCK_IDM = 131


def read_nfc_blocking(timeout: int = 30) -> dict | None:
    """
    Type-F (Felica) タグからIDMを取得する。
    戻り値:
        {
            "idm":      "012E50E6E84C625D",  # 16文字 hex文字列
            "idm_bytes": b'\x01\x2e...',      # 8バイト
            "pmm":      "00F10000000143​00",  # PMM 16文字 hex
            "uid":      "012E50E6E84C625D",  # tag.identifier (= IDM と同値)
        }
    タイムアウトまたは失敗時は None。
    """
    if not NFC_AVAILABLE:
        # ダミー (テストデータのIDMをそのまま使用)
        time.sleep(1)
        idm_bytes = bytes([0x01, 0x2e, 0x50, 0xe6, 0xe8, 0x4c, 0x62, 0x5d])
        pmm_bytes = bytes([0x00, 0xf1, 0x00, 0x00, 0x00, 0x01, 0x43, 0x00])
        return {
            "idm":       idm_bytes.hex().upper(),
            "idm_bytes": idm_bytes,
            "pmm":       pmm_bytes.hex().upper(),
            "uid":       idm_bytes.hex().upper(),
        }

    result = {}
    start = time.time()

    def on_connect(tag):
        # Type-F 以外は無視
        if not isinstance(tag, nfc.tag.tt3.Type3Tag):
            return False

        idm_raw = bytes(tag.identifier)  # nfcpy は identifier = IDM (8バイト)
        result["uid"] = idm_raw.hex().upper()

        # Read Without Encryption でブロック131を読み IDM+PMM を取得
        # (tag.identifier で IDM は既に取得済みだが、ブロック読みで整合性を確認)
        try:
            sc = nfc.tag.tt3.ServiceCode(0x000B, 0x0B)  # ランダムR/Wサービス
            bc = nfc.tag.tt3.BlockCode(BLOCK_IDM, service=0)
            data = tag.read_without_encryption([sc], [bc])
            block131 = bytes(data[0]) if data else None
        except Exception:
            block131 = None

        if block131 and len(block131) >= 16:
            idm_bytes = block131[0:8]
            pmm_bytes = block131[8:16]
        else:
            # ブロック読み取り失敗時は identifier から取得
            idm_bytes = idm_raw
            pmm_bytes = b'\x00' * 8

        result["idm"]       = idm_bytes.hex().upper()
        result["idm_bytes"] = idm_bytes
        result["pmm"]       = pmm_bytes.hex().upper()
        return True  # disconnect

    clf = nfc.ContactlessFrontend()
    try:
        clf.open(NFC_DEVICE)
        clf.connect(
            rdwr={
                "on-connect": on_connect,
                "targets": ["212F"],          # Type-F 212kbps のみ
            },
            terminate=lambda: bool(result) or (time.time() > start + timeout),
        )
    finally:
        clf.close()

    return result if result else None


# ─────────────────────────────────────────
# カメラ・撮影
# ─────────────────────────────────────────
def capture_face(student_id: str) -> str | None:
    """カメラから1フレーム取得し保存。パスを返す。"""
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    path = os.path.join(FACE_DIR, f"{student_id}.jpg")
    cv2.imwrite(path, frame)
    return path


def get_camera_frame() -> np.ndarray | None:
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        return None
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def ocr_student_id(frame: np.ndarray) -> str | None:
    """EasyOCRで学籍番号らしい文字列を抽出。"""
    if not OCR_AVAILABLE:
        return None
    reader = easyocr.Reader(["ja", "en"], gpu=False)
    results = reader.readtext(frame)
    for _, text, conf in results:
        cleaned = text.replace(" ", "").replace("-", "")
        # 英数字8〜12文字を学籍番号候補とする（学校仕様に合わせて調整）
        if conf > 0.6 and cleaned.isalnum() and 6 <= len(cleaned) <= 14:
            return cleaned
    return None


# ─────────────────────────────────────────
# GUI アプリ
# ─────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("学生証登録システム")
        self.attributes("-fullscreen", True)
        self.configure(bg="#0a0a14")
        self._font_large = tkfont.Font(family="Noto Sans CJK JP", size=28, weight="bold")
        self._font_mid = tkfont.Font(family="Noto Sans CJK JP", size=18)
        self._font_small = tkfont.Font(family="Noto Sans CJK JP", size=13)

        self.student_id = tk.StringVar()
        self.status_msg = tk.StringVar(value="")
        self._nfc_thread = None
        self._frame_container = tk.Frame(self, bg="#0a0a14")
        self._frame_container.pack(fill="both", expand=True)

        self.show_phase1()

    # ── ユーティリティ ──────────────────
    def clear(self):
        for w in self._frame_container.winfo_children():
            w.destroy()

    def label(self, parent, text, size="mid", fg="#e8e8f0", **kw):
        f = {"large": self._font_large, "mid": self._font_mid, "small": self._font_small}[size]
        return tk.Label(parent, text=text, font=f, fg=fg, bg="#0a0a14", **kw)

    def btn(self, parent, text, cmd, **kw):
        return tk.Button(
            parent, text=text, command=cmd,
            font=self._font_mid,
            bg="#1e90ff", fg="white",
            activebackground="#005fcc", activeforeground="white",
            relief="flat", padx=20, pady=10, cursor="hand2",
            **kw
        )

    def soft_key_row(self, parent, keys: list[str], entry_var: tk.StringVar):
        row = tk.Frame(parent, bg="#0a0a14")
        for k in keys:
            tk.Button(
                row, text=k, width=3,
                font=self._font_mid,
                bg="#1e1e2e", fg="#e8e8f0",
                activebackground="#2e2e4e",
                relief="flat",
                command=lambda c=k: entry_var.set(entry_var.get() + c)
            ).pack(side="left", padx=2, pady=2)
        return row

    # ── フェーズ１ ──────────────────────
    def show_phase1(self):
        self.clear()
        self.student_id.set("")
        f = self._frame_container

        self.label(f, "学生証登録", "large").pack(pady=(60, 10))
        self.label(f, "フェーズ１：学籍番号を入力", fg="#888").pack(pady=(0, 30))

        entry = tk.Entry(
            f, textvariable=self.student_id,
            font=self._font_large,
            bg="#1e1e2e", fg="#e8e8f0",
            insertbackground="white",
            relief="flat", width=20, justify="center"
        )
        entry.pack(pady=10)
        entry.focus_set()

        # ソフトキーボード
        kb_frame = tk.Frame(f, bg="#0a0a14")
        kb_frame.pack(pady=10)
        rows = [
            list("1234567890"),
            list("QWERTYUIOP"),
            list("ASDFGHJKL"),
            list("ZXCVBNM"),
        ]
        for row_keys in rows:
            self.soft_key_row(kb_frame, row_keys, self.student_id).pack()

        # BSキー
        tk.Button(
            kb_frame, text="⌫ 削除", width=8,
            font=self._font_mid, bg="#3a1e1e", fg="#e8e8f0",
            relief="flat",
            command=lambda: self.student_id.set(self.student_id.get()[:-1])
        ).pack(pady=4)

        err_label = tk.Label(f, textvariable=self.status_msg,
                             font=self._font_small, fg="#ff4444", bg="#0a0a14")
        err_label.pack(pady=4)

        # OCRボタン（カメラが使える場合の補助）
        ocr_btn = self.btn(f, "📷 カメラからOCR取得", self._ocr_from_camera)
        ocr_btn.pack(pady=6)

        self.btn(f, "次へ → NFCをかざす", self._phase1_next,
                 bg="#28a745").pack(pady=10)

    def _ocr_from_camera(self):
        self.status_msg.set("カメラ取得中...")
        frame = get_camera_frame()
        if frame is None:
            self.status_msg.set("カメラが使えません")
            return
        result = ocr_student_id(frame)
        if result:
            self.student_id.set(result)
            self.status_msg.set(f"OCR取得: {result}")
        else:
            self.status_msg.set("OCRで学籍番号を取得できませんでした。手動で入力してください。")

    def _phase1_next(self):
        sid = self.student_id.get().strip()
        if len(sid) < 4:
            self.status_msg.set("学籍番号が短すぎます")
            return
        self.status_msg.set("")
        self.show_phase2()

    # ── フェーズ２ ──────────────────────
    def show_phase2(self):
        self.clear()
        f = self._frame_container

        self.label(f, "フェーズ２：NFC読み取り", "large").pack(pady=(60, 20))
        self.label(f, f"学籍番号: {self.student_id.get()}", fg="#1e90ff").pack()
        self.label(f, "学生証をリーダーの上に置いてください").pack(pady=20)

        self._spinner_var = tk.StringVar(value="⏳ 読み取り待機中...")
        self.label(f, "", "small").pack()  # spacer
        spin_lbl = tk.Label(f, textvariable=self._spinner_var,
                            font=self._font_mid, fg="#ffcc00", bg="#0a0a14")
        spin_lbl.pack(pady=10)

        self._preview_label = tk.Label(f, bg="#0a0a14")
        self._preview_label.pack(pady=10)

        self._nfc_data = None
        self._face_path = None

        # NFC読み取りをバックグラウンドで開始
        self._nfc_thread = threading.Thread(target=self._nfc_worker, daemon=True)
        self._nfc_thread.start()

        # カメラプレビュー更新
        self._update_preview()

    def _nfc_worker(self):
        try:
            data = read_nfc_blocking(timeout=60)
        except Exception as e:
            data = None
            print(f"[NFC ERROR] {e}")

        if data:
            # 同時にカメラ撮影
            face_path = capture_face(self.student_id.get())
            self.after(0, self._phase2_done, data, face_path)
        else:
            self.after(0, self._phase2_error, "NFCの読み取りに失敗しました")

    def _update_preview(self):
        """カメラプレビューを定期更新（NFC待機中のみ）"""
        if not hasattr(self, "_preview_label"):
            return
        frame = get_camera_frame()
        if frame is not None:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(frame_rgb).resize((320, 240))
            imgtk = ImageTk.PhotoImage(image=img)
            self._preview_label.imgtk = imgtk
            self._preview_label.configure(image=imgtk)
        # スピナーアニメーション
        dots = getattr(self, "_dot_count", 0)
        self._dot_count = (dots + 1) % 4
        self._spinner_var.set("⏳ 読み取り待機中" + "." * self._dot_count)
        if self._nfc_thread and self._nfc_thread.is_alive():
            self.after(200, self._update_preview)

    def _phase2_done(self, nfc_data: dict, face_path: str | None):
        self._nfc_data = nfc_data
        self._face_path = face_path
        self.show_phase3()

    def _phase2_error(self, msg: str):
        self.status_msg.set(msg)
        self.show_phase4(success=False, error=msg)

    # ── フェーズ３ ──────────────────────
    def show_phase3(self):
        self.clear()
        f = self._frame_container

        self.label(f, "フェーズ３：データ保存中...", "large").pack(pady=(80, 20))

        try:
            sid = self.student_id.get().strip()
            save_record(sid, self._nfc_data, self._face_path or "")
            self.after(800, lambda: self.show_phase4(success=True))
        except Exception as e:
            self.after(0, lambda: self.show_phase4(success=False, error=str(e)))

    # ── フェーズ４ ──────────────────────
    def show_phase4(self, success: bool, error: str = ""):
        self.clear()
        f = self._frame_container

        if success:
            idm = self._nfc_data.get("idm", "N/A") if self._nfc_data else "N/A"
            self.label(f, "✅ 登録完了", "large", fg="#28a745").pack(pady=(80, 20))
            self.label(f, f"学籍番号: {self.student_id.get()}").pack(pady=4)
            self.label(f, f"IDM: {idm}", fg="#aaddff", size="small").pack(pady=4)
            self.label(f, "学生証をリーダーから取り外してください", fg="#ffcc00").pack(pady=20)
            self.btn(f, "次の登録へ", self.show_phase1).pack(pady=20)
        else:
            self.label(f, "❌ 登録失敗", "large", fg="#ff4444").pack(pady=(80, 20))
            self.label(f, f"エラー: {error}", fg="#ff8888").pack(pady=10)
            self.label(f, "フェーズ１からやり直してください").pack(pady=10)
            self.btn(f, "最初からやり直す", self.show_phase1, bg="#cc3333").pack(pady=20)

        self.btn(f, "終了", self.destroy, bg="#444").pack(pady=10)


# ─────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.mainloop()