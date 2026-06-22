import tkinter as tk
from tkinter import messagebox
import threading
import binascii
import time
import os

import nfc
import requests

# --- 設定 ---
# サーバーIPはファイルから読み込む（DHCPでIPが変わるため、起動時/送信時に毎回参照）
SERVER_IP_FILE = "serverIP.txt"
SERVER_PORT = 8001
SERVER_PATH = "/nfc/touch"
REQUEST_TIMEOUT = 5  # 秒

# --- カメラ / face_verify は一時的に無効化中 ---
# import cv2
# from face_verifier import verify_face


def read_server_ip():
    """serverIP.txt からサーバーIPを読み込む。"""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(base_dir, SERVER_IP_FILE)
    with open(path, "r", encoding="utf-8") as f:
        ip = f.read().strip()
    if not ip:
        raise ValueError(f"{SERVER_IP_FILE} が空です。サーバーIPを記入してください。")
    return ip


def build_server_url():
    """送信先URLを組み立てる。"""
    ip = read_server_ip()
    return f"http://{ip}:{SERVER_PORT}{SERVER_PATH}"


def send_card_uid(card_uid):
    """
    取得したIDm(card_uid)をサーバーへPOSTする。
    相当するcurl:
      curl -X POST -H "Content-Type: application/json" \
           -d "{\"card_uid\":\"XXXXXXX\"}" http://<IP>:8001/nfc/touch
    成功時 (True, メッセージ) / 失敗時 (False, メッセージ) を返す。
    """
    try:
        url = build_server_url()
    except Exception as e:
        return False, f"IP読込エラー: {e}"

    try:
        resp = requests.post(
            url,
            json={"card_uid": card_uid},
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            return True, f"送信成功 ({resp.status_code})"
        return False, f"サーバー応答エラー ({resp.status_code})"
    except requests.exceptions.RequestException as e:
        return False, f"送信失敗: {e}"


class NFCApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NFC 学生証リーダー (サーバー送信)")
        self.root.geometry("600x500")

        # フラグ: アプリが起動中かどうか
        self.is_running = True

        # 送信成功した件数
        self.sent_count = 0

        # --- GUIの構築 ---
        self.label_title = tk.Label(root, text="学生証をかざしてください", font=("Helvetica", 24))
        self.label_title.pack(pady=20)

        self.label_result_id = tk.Label(root, text="---", font=("Helvetica", 40, "bold"), fg="blue")
        self.label_result_id.pack(pady=10)

        self.label_count = tk.Label(root, text="送信件数: 0", font=("Helvetica", 14))
        self.label_count.pack(pady=10)

        self.label_status = tk.Label(root, text="リーダー接続中...", font=("Helvetica", 12), fg="gray")
        self.label_status.pack(pady=10)

        # 現在の送信先表示
        self.label_server = tk.Label(root, text="", font=("Helvetica", 10), fg="gray")
        self.label_server.pack(pady=5)
        self.refresh_server_label()

        # --- NFC読み取りスレッドの開始 ---
        self.thread = threading.Thread(target=self.nfc_thread_loop)
        self.thread.daemon = True
        self.thread.start()

        # ウィンドウを閉じる時の処理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def refresh_server_label(self):
        """送信先URLの表示を更新する。"""
        try:
            text = f"送信先: {build_server_url()}"
        except Exception as e:
            text = f"送信先未設定: {e}"
        self.label_server.config(text=text)

    def on_nfc_connect(self, tag):
        """カードがタッチされた時の処理（別スレッド）"""
        idm_bytes = tag.idm
        idm_hex = binascii.hexlify(idm_bytes).decode("ascii").upper()

        # サーバーへ送信
        ok, msg = send_card_uid(idm_hex)

        if ok:
            self.sent_count += 1
            self.root.after(0, lambda: self.update_gui("送信成功", idm_hex, "green", msg))
        else:
            self.root.after(0, lambda: self.update_gui("送信失敗", idm_hex, "red", msg))

        time.sleep(1.5)
        self.root.after(0, self.reset_gui)

        return True

    def nfc_thread_loop(self):
        """NFC読み取りループ（別スレッド）"""
        try:
            with nfc.ContactlessFrontend("usb") as clf:
                self.root.after(0, lambda: self.label_status.config(text="● 読み取り待機中", fg="gray"))
                while self.is_running:
                    clf.connect(
                        rdwr={"on-connect": self.on_nfc_connect},
                        terminate=lambda: not self.is_running,
                    )
                    time.sleep(0.1)
        except Exception as e:
            err_msg = f"エラー: {e}"
            print(err_msg)
            if self.is_running:
                self.root.after(0, lambda: self.label_status.config(text=err_msg, fg="red"))

    def update_gui(self, status_text, result_text, color, status_detail=""):
        """画面更新処理"""
        self.label_title.config(text=status_text)
        self.label_result_id.config(text=result_text, fg=color)
        self.label_count.config(text=f"送信件数: {self.sent_count}")
        if status_detail:
            self.label_status.config(text=status_detail, fg=color)

    def reset_gui(self):
        """画面リセット処理"""
        if not self.is_running:
            return
        self.label_title.config(text="学生証をかざしてください")
        self.label_result_id.config(text="---", fg="black")
        self.label_status.config(text="● 読み取り待機中", fg="gray")
        self.refresh_server_label()

    def on_closing(self):
        """終了処理"""
        self.is_running = False
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = NFCApp(root)
    root.mainloop()
