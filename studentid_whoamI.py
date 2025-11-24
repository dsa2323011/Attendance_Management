#出席確認用
#現段階では辞書型を使用


import nfc
import binascii
import sys
import os

# 照合用の学生証データ辞書
# 実際には、学籍番号と対応するIDmのデータを事前に準備しておく必要があります。
# フォーマット： { 'IDmの16進数文字列': '対応する学籍番号' }
#学籍番号と内部IDのデータベース
StudentIDs = {
            "012E50E6E84C626D":"2323010"
            "012E50E6E84C625D":"2323011"
            "012E50E6E84B303E":"2323019"
            "012E50E6E84B3139":"2323022"
            "012E50E6E84D498D":"2323033"
            "012E50E6E84D4DB7":"2323049"
            "012E50E6E84D4E38":"2323051"
            "012E5CE5D81676A4":"2323082"
            "012E50E6E84CC072":"2323087"
            "012E50E6E84CC073":"2323088"
            "012E50E6E84CC053":"2323091"
            "012E50E6E84CBD8C":"2323093"
            "012E50E6E84CBE71":"2323107"
            }

def on_connect(tag: nfc.tag.Tag) -> bool:
    """NFCタグが接続されたときに実行される関数。"""
    print("connected: カードのデータを処理中...")

    # FeliCaタグであることを確認 (Type3Tag)
    if tag.type != 'Type3Tag':
        print("\n⚠️ 読み取られたタグはFeliCaではありません。スキップします。")
        return False

    # IDm (製造ID) を取得
    # IDDデータとしてIDmを使用します。これはバイト列です。
    idm_bytes = tag.idm

    # IDmを16進数文字列に変換
    idm_hex = binascii.hexlify(idm_bytes).decode('ascii').upper()
    print(f"   読み取られたIDm: {idm_hex}")

    # 辞書と照合して学籍番号を取得
    found_student_id = STUDENT_IDS.get(idm_hex)
    
    if found_student_id:
        print("\n✅ 照合成功！")
        print(f"   対応する学籍番号: **{found_student_id}**")
        print(f"   カードの持ち主は {found_student_id} です。")
    else:
        print("\n❌ 照合失敗。")
        print("   このIDmに対応する学籍番号が見つかりませんでした。")
        print("   （辞書に登録されていない学生証です）")

    # Trueを返すとタグが離されるまで待機しますが、ここでは処理完了後にすぐに次のカードを待てるようにFalseを返すことで、
    # Enter待ちのステップに進めるようにします。
    return False

def on_release(tag: nfc.tag.Tag) -> None:
    """NFCタグが離されたときに実行される関数。"""
    pass

def main():
    """メイン処理"""
    print("NFCリーダを初期化中...")
    print(f"登録済み学生数: {len(STUDENT_IDS)}名")

    try:
        # 'usb'はLinuxで一般的なNFCリーダーの指定方法です。
        with nfc.ContactlessFrontend("usb") as clf:
            if not clf:
                print("❌ NFCリーダーが見つからないか、初期化できませんでした。", file=sys.stderr)
                return

            print("---")
            while True:
                print("▶️ **学生証をリーダーにかざしてください**...")

                # 接続を待機。on_connectが処理を行い、Falseを返して終了します。
                # terminate=lambda: False は、接続成功後にループを継続させるための慣用的な記述です。
                clf.connect(
                    rdwr={"on-connect": on_connect, "on-release": on_release},
                    terminate=lambda: False
                )
                
                # 読み取り完了後の待機
                # ユーザーが結果を確認し、Enterキーを押して次の読み取りに進めるようにします。
                input("\n↩️ **Enterキーを押して次の学生証の読み取りに進んでください**...")
                print("-" * 30)

    except KeyboardInterrupt:
        print("\n\nプログラムを終了します。")
    except Exception as e:
        print(f"\n致命的なエラーが発生しました: {e}", file=sys.stderr)

if __name__ == "__main__":
    main()