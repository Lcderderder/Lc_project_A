from PIL import Image
import os
import hashlib
import shutil
import logging
from sqlalchemy.exc import SQLAlchemyError
from models import db, Photo
from config import Config
from datetime import datetime

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------
# 基础工具函数
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

def generate_thumbnail(file_path, category, filename, file_hash):
    """生成缩略图，使用文件哈希值作为文件名"""
    _, ext = os.path.splitext(filename)
    thumb_filename = f"{file_hash}_thumb{ext.lower()}"
    thumb_path = get_thumbnail_path(category, thumb_filename)

    # 如果缩略图已存在，直接返回
    if os.path.exists(thumb_path):
        logger.info(f"缩略图已存在，跳过生成：{thumb_path}")
        return thumb_filename

    try:
        # 检查文件是否可读
        if not os.path.isfile(file_path) or not os.access(file_path, os.R_OK):
            raise Exception(f"文件不可读或不存在：{file_path}")
        
        img = Image.open(file_path)
        # 确保图片格式支持
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.thumbnail((300, 300))
        img.save(thumb_path)
        logger.info(f"生成缩略图成功：{thumb_path}")
        return thumb_filename
    except Exception as e:
        logger.error(f"生成缩略图失败（{category}/{filename}）：{str(e)}")
        # 容错：返回默认缩略图名
        return f"default_thumb{ext.lower()}"

def check_and_complement_thumbnail(photo_path, category, photo_filename, file_hash):
    """检查并补全缩略图"""
    logger.info(f"检查缩略图：{category}/{photo_filename}")
    return generate_thumbnail(photo_path, category, photo_filename, file_hash)

# ------------------------------
# 数据库+扫描函数
# ------------------------------
def init_database():
    """初始化数据库"""
    db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
    if os.path.exists(db_path):
        os.remove(db_path)
        logger.info(f"删除旧数据库：{db_path}")

    db.create_all()
    logger.info(f"新数据库 {db_path} 已创建")

def scan_photo_folder():
    """
    扫描照片文件夹并更新数据库
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

            # 计算文件哈希值
            file_hash = get_file_hash(photo_path)
            _, ext = os.path.splitext(filename)
            new_photo_filename = f"{file_hash}{ext.lower()}"
            new_photo_path = os.path.join(category_photo_folder, new_photo_filename)

            # 重命名文件（使用哈希值作为文件名）
            if not os.path.exists(new_photo_path):
                os.rename(photo_path, new_photo_path)
                logger.info(f"重命名文件：{filename} -> {new_photo_filename}")

            # 生成缩略图
            thumb_filename = check_and_complement_thumbnail(
                new_photo_path, category, new_photo_filename, file_hash
            )

            # 录入数据库
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
                logger.info(f"成功添加照片到数据库：{category}/{new_photo_filename}")
            except SQLAlchemyError as e:
                db.session.rollback()
                skipped_count += 1
                logger.error(f"数据库操作失败（{category}/{filename}）：{str(e)}")

    db.session.remove()
    result_msg = f"扫描完成：新增{added_count}张，跳过{skipped_count}张"
    logger.info(result_msg)
    return {
        "added": added_count,
        "skipped": skipped_count,
        "message": result_msg
    }
