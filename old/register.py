import nfc
import binascii
import os
import sys

# ファイル名の定義
OUTPUT_FILENAME = "student_id_data.txt"

def on_connect(tag: nfc.tag.Tag, student_id: str) -> bool:
    """
    NFCタグが接続されたときに実行される関数。
    学籍番号(student_id)を受け取るように変更しました。
    """
    print("connected: FeliCaカードのデータを処理中...")

    # FeliCaタグであるか確認
    if tag.type != 'Type3Tag':
        print("\n⚠️ 読み取られたタグはFeliCa (Type3Tag) ではありません。スキップします。")
        print(f"   タグタイプ: {tag.type}")
        return False

    # IDmとPMmをバイト列で取得
    idm_bytes = tag.idm
    pmm_bytes = tag.pmm

    # IDmとPMmを16進数文字列に変換 (10進数変換は削除)
    idm_hex = binascii.hexlify(idm_bytes).decode('ascii').upper()
    pmm_hex = binascii.hexlify(pmm_bytes).decode('ascii').upper()
    
    # 保存形式: 学籍番号:IDm(16進数),PMm(16進数)
    data_line = f"{student_id}:{idm_hex},{pmm_hex}"

    # データを.txt形式で保存（追記モード）
    try:
        with open(OUTPUT_FILENAME, 'a', encoding='utf-8') as f:
            f.write(data_line + "\n")
        
        print(f"\n✅ 読み取り完了: データをファイル '{OUTPUT_FILENAME}' に保存しました。")
        print(f"   保存データ: **{data_line}**")
        
    except IOError as e:
        print(f"\n❌ ファイル保存中にエラーが発生しました: {e}")

    # Falseを返すと、タグが離されるのを待たずに次の接続待機状態に移行
    return False

def on_release(tag: nfc.tag.Tag) -> None:
    """NFCタグが離されたときに実行される関数。"""
    pass

# ----------------------------------------------------------------------

def main():
    """メイン処理"""
    print("NFCリーダを初期化中...")
    print(f"読み取りデータは **'{OUTPUT_FILENAME}'** に保存されます。")
    
    # 既存ファイルの確認と新規作成
    if os.path.exists(OUTPUT_FILENAME):
        print(f"既存のファイルに追記します。")
    else:
        print(f"新規ファイルを作成します。")
        # ヘッダー行を書き込む (オプション)
        try:
             with open(OUTPUT_FILENAME, 'w', encoding='utf-8') as f:
                 f.write("Student_ID:IDm_Hex,PMm_Hex\n")
        except IOError as e:
             print(f"❌ ヘッダー書き込み中にエラーが発生しました: {e}")

    try:
        with nfc.ContactlessFrontend("usb") as clf:
            if not clf:
                print("❌ NFCリーダーが見つからないか、初期化できませんでした。")
                print("   Linux環境の場合、`sudo`での実行を試すか、ユーザーの権限を確認してください。")
                return

            print("---")
            while True:
                # ① 学籍番号の入力
                current_student_id = input("🔢 **学籍番号を入力してください** (Ctrl+Cで終了): ").strip()
                if not current_student_id:
                     print("⚠️ 学籍番号が入力されていません。")
                     continue

                print(f"▶️ 学籍番号 **{current_student_id}** の学生証をリーダーにかざしてください...")

                # ② NFC接続を待機。on_connectに学籍番号を渡すためにラムダ関数を使用
                # rdwr辞書内のon-connectに、引数を渡すラムダ関数を定義
                clf.connect(
                    rdwr={"on-connect": lambda tag: on_connect(tag, current_student_id)}, 
                    terminate=lambda: False
                )
                
                # ③ 読み取り完了後の待機
                input("\n↩️ **Enterキーを押して次の学生証の読み取りに進んでください**...")
                print("-" * 30)

    except KeyboardInterrupt:
        print("\n\nプログラムを終了します。")
    except Exception as e:
        print(f"\n致命的なエラーが発生しました: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()

