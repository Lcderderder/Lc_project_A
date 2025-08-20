from PIL import Image
import os
from flask import current_app
import secrets

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in current_app.config['ALLOWED_EXTENSIONS']

def save_photo(file):
    if file and allowed_file(file.filename):
        # 生成随机文件名
        random_hex = secrets.token_hex(8)
        _, ext = os.path.splitext(file.filename)
        filename = random_hex + ext.lower()
        
        # 保存原始图片
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)
        
        # 生成缩略图
        thumbnail = generate_thumbnail(file_path, filename)
        
        return filename, thumbnail
    return None, None

def generate_thumbnail(file_path, filename):
    # 生成缩略图文件名
    random_hex = secrets.token_hex(8)
    _, ext = os.path.splitext(filename)
    thumb_filename = random_hex + '_thumb' + ext.lower()
    thumb_path = os.path.join(current_app.config['THUMBNAIL_FOLDER'], thumb_filename)
    
    # 创建缩略图
    try:
        img = Image.open(file_path)
        img.thumbnail((300, 300))
        img.save(thumb_path)
        return thumb_filename
    except Exception as e:
        print(f"Error generating thumbnail: {e}")
        return None