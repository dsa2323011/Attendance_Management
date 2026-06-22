import nfc
import binascii
import sqlite3
import datetime
import time # 追加: 待機処理用

DB_NAME = "attendance.db"

def init_db():
    """データベースとテーブルの初期設定"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            idm TEXT PRIMARY KEY,
            student_id TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def get_student_id(idm):
    """IDmから学籍番号を検索する"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT student_id FROM students WHERE idm = ?", (idm,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def register_student(idm, student_id):
    """新しいカード(IDm)と学籍番号を名簿に登録する"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO students (idm, student_id) VALUES (?, ?)", (idm, student_id))
    conn.commit()
    conn.close()

def log_attendance(student_id):
    """学籍番号で出席を記録する"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT INTO logs (student_id, timestamp) VALUES (?, ?)", (student_id, now))
    conn.commit()
    conn.close()
    print(f"[{now}] 出席記録完了: 学籍番号 {student_id}")

# ※今回は on_connect を使いません。clf.connect() の戻り値を直接使います。

def main():
    init_db()
    print("データベースの準備が完了しました。")
    
    clf = None
    try:
        clf = nfc.ContactlessFrontend('usb')
        print("PaSoRiの準備が完了しました。")
        print("=== 出席受付を開始します (終了するには Ctrl+C) ===")
        
        # 前回のタッチしたIDmを保持して、連続二重タッチを防ぐ
        last_idm = None
        
        while True:
            # iterations=1 (1回だけポーリング), interval=0.5 (0.5秒間隔) で短時間だけ待機
            # カードがなければ None を返し、カードがあれば tag オブジェクトを返す
            tag = clf.connect(rdwr={'iterations': 1, 'interval': 0.5})
            
            if tag:
                idm = binascii.hexlify(tag.identifier).decode().upper()
                
                # 同じカードをずっと乗せている場合の二重記録を防ぐ
                if idm != last_idm:
                    student_id = get_student_id(idm)

                    if student_id:
                        print(f"\n学生証を認識しました！ 学籍番号: {student_id}")
                        log_attendance(student_id)
                    else:
                        print(f"\n未登録のカードです。(IDm: {idm})")
                        new_id = input("登録する学籍番号を入力してください (キャンセルはEnter): ")
                        
                        if new_id:
                            register_student(idm, new_id)
                            print(f"学籍番号 {new_id} を名簿に登録しました。")
                            log_attendance(new_id)
                        else:
                            print("登録をキャンセルしました。")
                    
                    last_idm = idm # 今回タッチしたIDmを記録
            else:
                # カードが離れたら last_idm をリセットし、次の人のタッチを受け付ける
                last_idm = None
                
            # 少しだけスリープを入れてCPU負荷を下げる
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        # Ctrl+C を確実にここでキャッチできるようになります
        print("\n\nシステムを終了します。お疲れ様でした。")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    finally:
        if clf:
            clf.close()

if __name__ == '__main__':
    main()