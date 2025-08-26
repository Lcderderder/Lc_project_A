import os
from PIL import Image
from flask import current_app

# 允许的图片文件后缀（与config一致）
def allowed_file(filename):
    """检查文件是否为支持的图片类型"""
    if not filename:
        return False
    # 安全地获取文件扩展名
    if '.' not in filename:
        return False
    ext = filename.rsplit('.', 1)[1].lower()
    return ext in current_app.config['ALLOWED_EXTENSIONS']

def create_thumbnail(src_path, dest_path, size=None):
    """生成缩略图并保存"""
    try:
        # 验证源文件存在且可读
        if not os.path.exists(src_path) or not os.access(src_path, os.R_OK):
            current_app.logger.error(f"无法读取源文件: {src_path}")
            return False
            
        size = size or current_app.config['THUMBNAIL_MAX_SIZE']
        
        # 验证图片完整性
        try:
            with Image.open(src_path) as img:
                img.verify()  # 验证文件完整性
        except (IOError, SyntaxError) as e:
            current_app.logger.error(f"损坏的图片文件: {src_path} - {str(e)}")
            return False
        
        # 重新打开图片进行处理
        with Image.open(src_path) as img:
            # 转换模式（如果需要）
            if img.mode not in ('RGB', 'L'):
                img = img.convert('RGB')
            
            # 保持比例缩放
            img.thumbnail(size)
            
            # 创建目标目录（如果不存在）
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            
            # 保存缩略图
            img.save(dest_path, optimize=True, quality=85)
            
        return True
    except Exception as e:
        current_app.logger.error(f"生成缩略图失败 {src_path} -> {dest_path}: {str(e)}")
        return False

def scan_photo_folder(app):
    """扫描照片目录，生成缩略图并更新数据库"""
    from models import db, Photo

    photo_root = app.config['PHOTO_FOLDER']
    thumbnail_root = app.config['THUMBNAIL_FOLDER']
    new_count = 0
    update_count = 0
    error_count = 0

    # 确保缩略图根目录存在
    os.makedirs(thumbnail_root, exist_ok=True)

    try:
        all_items = os.listdir(photo_root)
    except (FileNotFoundError, PermissionError) as e:
        current_app.logger.error(f"无法访问照片根目录: {photo_root} - {str(e)}")
        return {"message": f"错误：无法访问照片根目录 '{photo_root}'", "new": 0, "updated": 0, "errors": 1}

    # 首先获取数据库中所有现有照片的映射，避免重复查询
    existing_photos_map = {}
    all_existing_photos = Photo.query.all()
    for photo in all_existing_photos:
        key = f"{photo.category}/{photo.filename}"
        existing_photos_map[key] = photo

    # 遍历photo文件夹下的所有子目录
    for item in all_items:
        item_path = os.path.join(photo_root, item)
        
        # 跳过非目录、隐藏文件和thumbnails目录
        if (not os.path.isdir(item_path) or 
            item.startswith(('.', '~')) or 
            item == 'thumbnails'):
            continue
        
        category = item
        current_app.logger.info(f"开始扫描分类: {category}")
        
        # 确保分类缩略图目录存在
        category_thumb_dir = os.path.join(thumbnail_root, category)
        os.makedirs(category_thumb_dir, exist_ok=True)
        
        try:
            category_files = os.listdir(item_path)
        except (PermissionError, NotADirectoryError) as e:
            current_app.logger.error(f"无法访问分类目录 '{item_path}': {e}")
            error_count += 1
            continue
            
        # 遍历分类目录下的文件
        for filename in category_files:
            file_path = os.path.join(item_path, filename)
            
            # 跳过隐藏文件和目录，只处理文件
            if (filename.startswith(('.', '~')) or not os.path.isfile(file_path)):
                continue
            
            # 只处理允许的图片文件
            if not allowed_file(filename):
                current_app.logger.debug(f"跳过不支持的文件类型: {filename}")
                continue
            
            # 检查数据库中是否已存在该照片（使用预先构建的映射）
            photo_key = f"{category}/{filename}"
            existing_photo = existing_photos_map.get(photo_key)
            
            # 定义缩略图路径
            thumbnail_path = os.path.join(category_thumb_dir, filename)
            
            # 生成缩略图（如果不存在，或者原图比缩略图新）
            need_generate_thumbnail = False
            thumbnail_generated = False

            if not os.path.exists(thumbnail_path):
                need_generate_thumbnail = True
                current_app.logger.info(f"缩略图不存在，将生成: {thumbnail_path}")
            else:
                try:
                    orig_mtime = os.path.getmtime(file_path)
                    thumb_mtime = os.path.getmtime(thumbnail_path)
                    if orig_mtime > thumb_mtime:
                        need_generate_thumbnail = True
                        current_app.logger.info(f"原图已更新，重新生成缩略图: {filename}")
                except OSError as e:
                    current_app.logger.error(f"无法获取文件修改时间: {file_path} 或 {thumbnail_path}, {e}")
                    need_generate_thumbnail = True

            if need_generate_thumbnail:
                if create_thumbnail(file_path, thumbnail_path):
                    thumbnail_generated = True
                    current_app.logger.info(f"已生成/更新缩略图: {thumbnail_path}")
                else:
                    error_count += 1
                    current_app.logger.error(f"生成缩略图失败，跳过文件: {file_path}")
                    continue
            
            if existing_photo:
                # 如果缩略图是新生成的，更新数据库记录
                if thumbnail_generated:
                    existing_photo.thumbnail = filename
                    update_count += 1
                    current_app.logger.debug(f"更新数据库记录: {category}/{filename}")
            else:
                # 新增照片记录
                photo_title = os.path.splitext(filename)[0]
                new_photo = Photo(
                    title=photo_title,
                    filename=filename,
                    thumbnail=filename,
                    category=category
                )
                db.session.add(new_photo)
                new_count += 1
                current_app.logger.info(f"新增数据库记录: {category}/{filename}")
                # 添加到映射中避免重复添加
                existing_photos_map[photo_key] = new_photo
    
    try:
        db.session.commit()
        result_msg = f"扫描完成，新增 {new_count} 张照片，更新 {update_count} 张照片记录，遇到 {error_count} 个错误"
        current_app.logger.info(result_msg)
        return {
            "message": result_msg,
            "new": new_count,
            "updated": update_count,
            "errors": error_count
        }
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"数据库提交失败: {str(e)}")
        return {
            "message": f"扫描失败（数据库错误）: {str(e)}",
            "new": 0,
            "updated": 0,
            "errors": error_count + 1
        }
        
