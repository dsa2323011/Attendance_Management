import face_recognition
import os
import cv2

def verify_face(current_frame, student_id, img_dir):
    """
    現在のフレームと、保存されている既存の顔写真を比較する
    """
    student_folder = os.path.join(img_dir, student_id)
    
    # 既存の写真リストを取得
    existing_files = [f for f in os.listdir(student_folder) if f.endswith(".jpg")]
    
    if not existing_files:
        return "NEW_REGISTER", None
    
    # 一番古い写真（初回撮影分）をマスター（正解）として使用
    existing_files.sort()
    master_path = os.path.join(student_folder, existing_files[0])
    
    try:
        # マスター画像の読み込みとエンコード
        master_image = face_recognition.load_image_file(master_path)
        master_encodings = face_recognition.face_encodings(master_image)
        
        # 今回撮影した画像のエンコード
        current_encodings = face_recognition.face_encodings(current_frame)
        
        if not master_encodings:
            return "ERROR", "マスター画像から顔が検出できません"
        if not current_encodings:
            return "ERROR", "カメラから顔が検出できません"
            
        # 比較 (toleranceは厳しさ。0.6が標準。小さいほど厳しい)
        results = face_recognition.compare_faces([master_encodings[0]], current_encodings[0], tolerance=0.5)
        
        # 距離（似ている度合い）も取得可能
        face_distance = face_recognition.face_distance([master_encodings[0]], current_encodings[0])[0]
        
        if results[0]:
            return "MATCH", face_distance
        else:
            return "MISMATCH", face_distance
            
    except Exception as e:
        return "ERROR", str(e)