import nfc
import binascii
import sqlite3
import datetime

DB_NAME = "attendance.db"

def init_db():
    """データベースとテーブルの初期設定"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # 1. 学生名簿テーブル (IDmと学籍番号の紐付け)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            idm TEXT PRIMARY KEY,
            student_id TEXT NOT NULL
        )
    ''')
    
    # 2. 出席ログテーブル (記録するのはIDmではなく学籍番号にする)
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

def on_connect(tag):
    """カードがタッチされた時の処理"""
    try:
        idm = binascii.hexlify(tag.identifier).decode().upper()
        
        # データベースから学籍番号を探す
        student_id = get_student_id(idm)

        if student_id:
            # パターンA: すでに登録されている場合
            print(f"\n学生証を認識しました！ 学籍番号: {student_id}")
            log_attendance(student_id)
        else:
            # パターンB: 未登録の新しいカードの場合
            print(f"\n未登録のカードです。(IDm: {idm})")
            new_id = input("登録する学籍番号を入力してください (キャンセルはEnter): ")
            
            if new_id:
                register_student(idm, new_id)
                print(f"学籍番号 {new_id} を名簿に登録しました。")
                log_attendance(new_id)
            else:
                print("登録をキャンセルしました。")
                
    except Exception as e:
        print(f"読み取りエラー: {e}")
        
    return True 

def main():
    init_db()
    print("データベースの準備が完了しました。")
    
    try:
        clf = nfc.ContactlessFrontend('usb')
        print("PaSoRiの準備が完了しました。")
        print("=== 出席受付を開始します (終了するには Ctrl+C) ===")
        
        while True:
            clf.connect(rdwr={'on-connect': on_connect})
            
    except KeyboardInterrupt:
        print("\nシステムを終了します。お疲れ様でした。")
    except Exception as e:
        print(f"エラーが発生しました: {e}")
    finally:
        if 'clf' in locals() and clf:
            clf.close()

if __name__ == '__main__':
    main()