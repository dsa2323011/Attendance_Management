import tkinter as tk
from tkinter import messagebox
import threading
import nfc
import binascii
import time
import csv
import os
import datetime

# 別のファイルから辞書を読み込む
# studentsID_DB.py が同じフォルダにある必要があります
from studentsID_DB import studentsID

class NFCApp:
    def __init__(self, root):
        self.root = root
        self.root.title("NFC 学生証リーダー (学籍番号のみ記録)")
        self.root.geometry("600x500")

        # フラグ: アプリが起動中かどうか
        self.is_running = True

        # 読み取ったデータを一時保存するリスト
        self.scanned_data = [] 

        # --- GUIの構築 ---
        
        # タイトル
        self.label_title = tk.Label(root, text="学生証をかざしてください", font=("Helvetica", 24))
        self.label_title.pack(pady=20)

        # 結果表示用のラベル
        self.label_result_id = tk.Label(root, text="---", font=("Helvetica", 40, "bold"), fg="blue")
        self.label_result_id.pack(pady=10)

        # 読み取り件数表示
        self.label_count = tk.Label(root, text="読み取り件数: 0", font=("Helvetica", 14))
        self.label_count.pack(pady=10)

        # ステータス表示
        self.label_status = tk.Label(root, text="リーダー接続中...", font=("Helvetica", 12), fg="gray")
        self.label_status.pack(pady=10)

        # エクスポートボタン
        self.btn_export = tk.Button(root, text="CSVエクスポート", command=self.export_csv, 
                                    font=("Helvetica", 14), bg="#dddddd", height=2, width=20)
        self.btn_export.pack(side=tk.BOTTOM, pady=30)

        # --- NFC読み取りスレッドの開始 ---
        self.thread = threading.Thread(target=self.nfc_thread_loop)
        self.thread.daemon = True
        self.thread.start()

        # ウィンドウを閉じる時の処理
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def on_nfc_connect(self, tag):
        """カードがタッチされた時の処理（別スレッド）"""
        idm_bytes = tag.idm
        idm_hex = binascii.hexlify(idm_bytes).decode('ascii').upper()

        student_id = studentsID.get(idm_hex)

        if student_id:
            self.scanned_data.append([student_id])
            self.update_gui("成功", student_id, "green")
        else:
            self.update_gui("未登録", "未登録カード", "red")

        time.sleep(1.5)
        self.reset_gui()
        
        return True

    def nfc_thread_loop(self):
        """NFC読み取りループ（別スレッド）"""
        try:
            with nfc.ContactlessFrontend('usb') as clf:
                self.root.after(0, lambda: self.label_status.config(text="● 読み取り待機中"))
                while self.is_running:
                    clf.connect(rdwr={'on-connect': self.on_nfc_connect}, 
                                terminate=lambda: not self.is_running)
                    time.sleep(0.1)
        except Exception as e:
            err_msg = f"エラー: {e}"
            print(err_msg)
            if self.is_running:
                self.root.after(0, lambda: self.label_status.config(text=err_msg, fg="red"))

    def update_gui(self, status_text, result_text, color):
        """画面更新処理"""
        self.label_title.config(text=status_text)
        self.label_result_id.config(text=result_text, fg=color)
        
        count_text = f"読み取り件数: {len(self.scanned_data)}"
        self.label_count.config(text=count_text)

    def reset_gui(self):
        """画面リセット処理"""
        if not self.is_running: return
        self.label_title.config(text="学生証をかざしてください")
        self.label_result_id.config(text="---", fg="black")

    def export_csv(self):
        """データをCSVに書き出す処理（savedフォルダへ保存）"""
        if not self.scanned_data:
            messagebox.showwarning("警告", "保存するデータがありません。")
            return

        try:
            # 1. 保存先フォルダ 'saved' の準備
            save_dir = "saved"
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)
                print(f"フォルダ '{save_dir}' を作成しました。")

            # 2. 現在時刻の取得とファイル名の生成
            now = datetime.datetime.now()
            # ファイル名: 出席名簿_2023-10-25_14-30-05.csv のような形式
            filename = now.strftime("出席名簿_%Y-%m-%d_%H-%M-%S.csv")
            filepath = os.path.join(save_dir, filename)

            # 3. CSV書き込み
            # encoding='utf-8-sig' はExcelで日本語が文字化けしないための設定です
            with open(filepath, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                
                # ★要件: 最初に保存時刻を出力
                save_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
                writer.writerow(["保存日時", save_time_str])
                writer.writerow([]) # 空行を一つ入れる（見やすさのため）
                
                # ヘッダーとデータ
                writer.writerow(["student ID"])
                writer.writerows(self.scanned_data)
            
            messagebox.showinfo("成功", f"データを保存しました。\n\n場所: {save_dir}\nファイル名: {filename}")
            
        except Exception as e:
            messagebox.showerror("エラー", f"保存中にエラーが発生しました:\n{e}")

    def on_closing(self):
        """終了処理"""
        self.is_running = False
        self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = NFCApp(root)
    root.mainloop()