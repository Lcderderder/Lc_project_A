import os
import logging
from flask_sqlalchemy import SQLAlchemy

logger = logging.getLogger(__name__)
db = SQLAlchemy()

class Photo(db.Model):
    __tablename__ = 'photos'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(255), nullable=False)  # 照片标题
    description = db.Column(db.Text, nullable=True)    # 照片描述（可选）
    filename = db.Column(db.String(255), nullable=False)  # 原图文件名
    thumbnail = db.Column(db.String(255), nullable=True)  # 缩略图文件名（可选，默认同原图）
    category = db.Column(db.String(100), nullable=False)  # 分类（对应文件夹名）

    def to_dict(self):
        """转换为字典，供前端API使用"""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'thumbnail': self.thumbnail or self.filename,  # 默认使用原图文件名
            'category': self.category
        }
    
    def delete_files(self, app_config):
        """删除对应的原图和缩略图文件（带路径安全检查）"""
        # 安全路径拼接（防止路径遍历攻击）
        def safe_join(base, *paths):
            try:
                full_path = os.path.join(base, *paths)
                if not full_path.startswith(base):
                    logger.warning(f"潜在的路径遍历攻击: {base} + {paths}")
                    return None
                return full_path
            except Exception as e:
                logger.error(f"路径拼接错误: {str(e)}")
                return None

        # 删除原图
        if self.filename and self.category:
            photo_path = safe_join(app_config['PHOTO_FOLDER'], self.category, self.filename)
            if photo_path and os.path.exists(photo_path) and os.path.isfile(photo_path):
                try:
                    os.remove(photo_path)
                    logger.info(f"已删除原图: {photo_path}")
                except Exception as e:
                    logger.error(f"删除原图失败 ({photo_path}): {str(e)}")

        # 删除缩略图
        if (self.thumbnail or self.filename) and self.category:
            thumb_filename = self.thumbnail or self.filename
            thumb_path = safe_join(app_config['THUMBNAIL_FOLDER'], self.category, thumb_filename)
            if thumb_path and os.path.exists(thumb_path) and os.path.isfile(thumb_path):
                try:
                    os.remove(thumb_path)
                    logger.info(f"已删除缩略图: {thumb_path}")
                except Exception as e:
                    logger.error(f"删除缩略图失败 ({thumb_path}): {str(e)}")