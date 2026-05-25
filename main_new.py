import tkinter as tk
from tkinter import messagebox
import threading
import nfc
import binascii
import time
import csv
import os
import datetime
import cv2
# 新しいファイルをインポート
from face_verifier import verify_face
from studentsID_DB import studentsID

class NFCApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NFC 学生証リーダー (顔認証付)")
        self.root.geometry("600x550")

        self.is_running = True
        self.scanned_data = [] 
        self.current_frame = None 
        self.img_dir = "img"

        # イニシャライズ（削除）を廃止し、フォルダ作成のみ行う
        if not os.path.exists(self.img_dir):
            os.makedirs(self.img_dir)

        # カメラ起動
        self.cap = cv2.VideoCapture(0)
        self.update_camera()

        # GUI構築
        self.label_title = tk.Label(root, text="学生証をかざしてください", font=("Helvetica", 20))
        self.label_title.pack(pady=10)

        self.label_result_id = tk.Label(root, text="---", font=("Helvetica", 32, "bold"), fg="blue")
        self.label_result_id.pack(pady=5)

        # 認証ステータス表示用
        self.label_auth = tk.Label(root, text="", font=("Helvetica", 16, "bold"))
        self.label_auth.pack(pady=5)

        self.label_count = tk.Label(root, text="読み取り件数: 0", font=("Helvetica", 12))
        self.label_count.pack(pady=5)

        self.label_status = tk.Label(root, text="リーダー待機中...", font=("Helvetica", 10), fg="gray")
        self.label_status.pack(pady=5)

        self.btn_export = tk.Button(root, text="CSVエクスポート", command=self.export_csv, font=("Helvetica", 14))
        self.btn_export.pack(side=tk.BOTTOM, pady=20)

        self.thread = threading.Thread(target=self.nfc_thread_loop)
        self.thread.daemon = True
        self.thread.start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def update_camera(self):
        if self.is_running and self.cap.isOpened():
            ret, frame = self.cap.read()
            if ret:
                self.current_frame = frame
        if self.is_running:
            self.root.after(30, self.update_camera)

    def on_nfc_connect(self, tag):
        idm_hex = binascii.hexlify(tag.idm).decode('ascii').upper()
        student_id = studentsID.get(idm_hex)

        if student_id:
            # 学籍番号ごとのフォルダ作成
            student_folder = os.path.join(self.img_dir, student_id)
            if not os.path.exists(student_folder):
                os.makedirs(student_folder)

            # 顔認証実行
            status, detail = verify_face(self.current_frame, student_id, self.img_dir)

            # 保存処理
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}.jpg"
            filepath = os.path.join(student_folder, filename)
            cv2.imwrite(filepath, self.current_frame)

            # GUI表示の更新
            self.scanned_data.append([student_id, status])
            self.update_gui(student_id, status)

            # 確認用ウィンドウ表示
            cv2.imshow('Verification', self.current_frame)
            cv2.waitKey(2000)
            cv2.destroyWindow('Verification')
        else:
            self.update_gui("未登録", "INVALID")
            time.sleep(2)

        self.reset_gui()
        return True

    def update_gui(self, student_id, status):
        self.label_result_id.config(text=student_id)
        
        if status == "MATCH":
            self.label_auth.config(text="本人確認成功", fg="green")
        elif status == "MISMATCH":
            self.label_auth.config(text="【警告】別人です", fg="red")
        elif status == "NEW_REGISTER":
            self.label_auth.config(text="初回登録完了", fg="blue")
        else:
            self.label_auth.config(text=f"認証エラー: {detail}", fg="orange")
            
        self.label_count.config(text=f"読み取り件数: {len(self.scanned_data)}")

    def reset_gui(self):
        if not self.is_running: return
        self.label_auth.config(text="")
        self.label_result_id.config(text="---", fg="black")

    def nfc_thread_loop(self):
        try:
            with nfc.ContactlessFrontend('usb') as clf:
                while self.is_running:
                    clf.connect(rdwr={'on-connect': self.on_nfc_connect}, 
                                terminate=lambda: not self.is_running)
                    time.sleep(0.1)
        except Exception as e:
            print(f"NFC Error: {e}")

    def export_csv(self):
        # (以前のコードと同様ですが、status列を追加した方が便利です)
        # 略
        pass

    def on_closing(self):
        self.is_running = False
        if self.cap.isOpened(): self.cap.release()
        cv2.destroyAllWindows()
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = NFCApp(root)
    root.mainloop()