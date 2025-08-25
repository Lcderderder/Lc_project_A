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
    """计算文件哈希值，增加错误处理"""
    try:
        hash_md5 = hashlib.md5()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(4096), b''):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    except Exception as e:
        logger.error(f"计算文件哈希失败 {file_path}: {str(e)}")
        # 使用文件名和时间戳作为备用哈希
        return hashlib.md5(f"{os.path.basename(file_path)}_{datetime.now().timestamp()}".encode()).hexdigest()

def get_thumbnail_path(category, thumb_filename):
    thumb_category_folder = os.path.join(Config.THUMBNAIL_FOLDER, category)
    os.makedirs(thumb_category_folder, exist_ok=True)
    return os.path.join(thumb_category_folder, thumb_filename)

def generate_thumbnail(file_path, category, filename, file_hash):
    """生成缩略图，使用文件哈希值作为文件名，增强容错"""
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
        img.thumbnail(Config.THUMBNAIL_MAX_SIZE)
        img.save(thumb_path)
        logger.info(f"生成缩略图成功：{thumb_path}")
        return thumb_filename
    except Exception as e:
        logger.error(f"生成缩略图失败（{category}/{filename}）：{str(e)}")
        # 容错：使用静态文件夹中的默认缩略图
        default_thumb = "default_thumbnail.jpg"
        default_thumb_path = os.path.join(Config.STATIC_FOLDER, default_thumb)
        # 确保默认缩略图存在
        if not os.path.exists(default_thumb_path):
            logger.warning(f"默认缩略图不存在，请在 {Config.STATIC_FOLDER} 放置 {default_thumb}")
        return default_thumb

def check_and_complement_thumbnail(photo_path, category, photo_filename, file_hash):
    """检查并补全缩略图"""
    logger.info(f"检查缩略图：{category}/{photo_filename}")
    return generate_thumbnail(photo_path, category, photo_filename, file_hash)

# ------------------------------
# 数据库+扫描函数
# ------------------------------
def init_database(app):
    """初始化数据库，需要传入Flask app实例"""
    try:
        db_path = Config.SQLALCHEMY_DATABASE_URI.replace('sqlite:///', '')
        if os.path.exists(db_path):
            os.remove(db_path)
            logger.info(f"删除旧数据库：{db_path}")

        # 确保在应用上下文中创建数据库
        with app.app_context():
            db.create_all()
            logger.info(f"新数据库 {db_path} 已创建")
        return True
    except Exception as e:
        logger.error(f"初始化数据库失败: {str(e)}")
        return False

def scan_photo_folder(app):
    """
    扫描照片文件夹并更新数据库，需要传入Flask app实例
    """
    logger.info("开始扫描照片文件夹...")
    
    # 1. 初始化数据库
    if not init_database(app):
        logger.error("数据库初始化失败")
        return {"added": 0, "skipped": 0, "message": "数据库初始化失败"}

    # 2. 遍历分类文件夹
    photo_root = Config.PHOTO_FOLDER
    try:
        categories = [
            f for f in os.listdir(photo_root) 
            if os.path.isdir(os.path.join(photo_root, f)) and f != 'thumbnails'
        ]
        logger.info(f"找到分类: {categories}")
    except Exception as e:
        logger.error(f"读取分类文件夹失败: {str(e)}")
        return {"added": 0, "skipped": 0, "message": f"读取分类文件夹失败: {str(e)}"}
        
    if not categories:
        logger.warning("未找到分类文件夹")
        return {"added": 0, "skipped": 0, "message": "未找到分类文件夹（需在photo下创建子文件夹）"}

    added_count = 0
    skipped_count = 0

    # 3. 处理每张照片（在应用上下文中执行）
    with app.app_context():
        for category in categories:
            category_photo_folder = os.path.join(photo_root, category)
            logger.info(f"处理分类: {category}")
            
            # 确保缩略图文件夹存在
            try:
                os.makedirs(os.path.join(Config.THUMBNAIL_FOLDER, category), exist_ok=True)
            except Exception as e:
                logger.error(f"创建缩略图文件夹失败 {category}: {str(e)}")
                continue

            try:
                files = os.listdir(category_photo_folder)
                logger.info(f"分类 {category} 中找到 {len(files)} 个文件")
            except Exception as e:
                logger.error(f"读取分类文件夹失败 {category}: {str(e)}")
                continue

            for filename in files:
                photo_path = os.path.join(category_photo_folder, filename)

                # 跳过子文件夹/不支持格式
                if os.path.isdir(photo_path):
                    skipped_count += 1
                    continue
                if not allowed_file(filename):
                    skipped_count += 1
                    continue

                try:
                    # 计算文件哈希值
                    file_hash = get_file_hash(photo_path)
                    _, ext = os.path.splitext(filename)
                    new_photo_filename = f"{file_hash}{ext.lower()}"
                    new_photo_path = os.path.join(category_photo_folder, new_photo_filename)

                    # 重命名文件（使用哈希值作为文件名）
                    if not os.path.exists(new_photo_path) and photo_path != new_photo_path:
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
                except Exception as e:
                    skipped_count += 1
                    logger.error(f"处理照片失败（{category}/{filename}）：{str(e)}")

        db.session.remove()

    result_msg = f"扫描完成：新增{added_count}张，跳过{skipped_count}张"
    logger.info(result_msg)
    return {
        "added": added_count,
        "skipped": skipped_count,
        "message": result_msg
    }
