from PIL import Image
import os
import hashlib
import shutil
import secrets
from sqlalchemy.exc import SQLAlchemyError
from models import db, Photo
from config import Config

# ------------------------------
# 基础工具函数（不变）
# ------------------------------
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS

def get_file_hash(file_path):
    hash_md5 = hashlib.md5()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(4096), b''):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def get_thumbnail_path(category, thumb_filename):
    thumb_category_folder = os.path.join(Config.THUMBNAIL_FOLDER, category)
    os.makedirs(thumb_category_folder, exist_ok=True)
    return os.path.join(thumb_category_folder, thumb_filename)

def generate_thumbnail(file_path, category, filename):
    random_hex = secrets.token_hex(8)
    _, ext = os.path.splitext(filename)
    thumb_filename = f"{random_hex}_thumb{ext.lower()}"
    thumb_path = get_thumbnail_path(category, thumb_filename)

    try:
        # 新增：检查文件是否可读
        if not os.path.isfile(file_path) or not os.access(file_path, os.R_OK):
            raise Exception(f"文件不可读或不存在：{file_path}")
        
        img = Image.open(file_path)
        # 新增：确保图片格式支持（避免PNG透明通道等问题）
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')  # 转为RGB格式，避免保存失败
        img.thumbnail((300, 300))
        img.save(thumb_path)
        print(f"生成缩略图成功：{thumb_path}")  # 日志：确认生成路径
        return thumb_filename
    except Exception as e:
        print(f"生成缩略图失败（{category}/{filename}）：{str(e)}")  # 打印具体错误
        # 容错：返回默认缩略图名（避免前端路径为空）
        return f"default_thumb{ext.lower()}"

def check_and_complement_thumbnail(photo_path, category, photo_filename, thumb_filename):
    # 强制生成新缩略图（不依赖旧文件名，避免空值）
    print(f"检查缩略图：{category}/{photo_filename}")
    return generate_thumbnail(photo_path, category, photo_filename)


# ------------------------------
# 数据库+扫描函数（依赖app.py的全局锁，确保串行）
# ------------------------------
def init_database():
    """初始化数据库（仅被scan_photo_folder调用，已在app.py加锁）"""
    db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"删除旧数据库：{db_path}")

    db.create_all()
    print(f"新数据库 {db_path} 已创建")

def scan_photo_folder():
    """
    扫描函数：
    - 已在app.py的auto_scan_after_start中加锁，确保无并发
    - 无需重复加锁，避免死锁
    """
    # 1. 初始化数据库
    init_database()

    # 2. 遍历分类文件夹
    photo_root = Config.PHOTO_FOLDER
    categories = [
        f for f in os.listdir(photo_root) 
        if os.path.isdir(os.path.join(photo_root, f)) and f != 'thumbnails'
    ]
    if not categories:
        return {"added": 0, "skipped": 0, "message": "未找到分类文件夹（需在photo下创建子文件夹）"}

    added_count = 0
    skipped_count = 0

    # 3. 处理每张照片
    for category in categories:
        category_photo_folder = os.path.join(photo_root, category)
        os.makedirs(os.path.join(Config.THUMBNAIL_FOLDER, category), exist_ok=True)

        for filename in os.listdir(category_photo_folder):
            photo_path = os.path.join(category_photo_folder, filename)

            # 跳过子文件夹/不支持格式
            if os.path.isdir(photo_path):
                skipped_count += 1
                continue
            if not allowed_file(filename):
                skipped_count += 1
                continue

            # 生成唯一文件名
            file_hash = get_file_hash(photo_path)
            _, ext = os.path.splitext(filename)
            new_photo_filename = f"hash_{file_hash}{ext.lower()}"
            new_photo_path = os.path.join(category_photo_folder, new_photo_filename)

            # 复制文件（防重名）
            if not os.path.exists(new_photo_path):
                shutil.copy2(photo_path, new_photo_path)

            # 补全缩略图
            thumb_filename = check_and_complement_thumbnail(
                new_photo_path, category, new_photo_filename, None
            )

            # 录入数据库（已在app.py加锁，无需额外处理）
            try:
                new_photo = Photo(
                    title=os.path.splitext(filename)[0],
                    description=f"分类：{category}",
                    filename=new_photo_filename,
                    thumbnail=thumb_filename,
                    category=category
                )
                db.session.add(new_photo)
                db.session.commit()
                added_count += 1
            except SQLAlchemyError as e:
                db.session.rollback()
                skipped_count += 1

    db.session.remove()
    return {
        "added": added_count,
        "skipped": skipped_count,
        "message": f"扫描完成：新增{added_count}张，跳过{skipped_count}张"
    }
