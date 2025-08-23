from flask_sqlalchemy import SQLAlchemy
import os
from logger import setup_logger

db = SQLAlchemy()
logger = setup_logger(__name__)

class Photo(db.Model):
    __tablename__ = 'photos'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    filename = db.Column(db.String(100), nullable=False)
    thumbnail = db.Column(db.String(100))
    category = db.Column(db.String(50), nullable=False)

    def to_dict(self):
        """转换为字典（适配前端）"""
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'thumbnail': self.thumbnail,
            'category': self.category
        }
    
    def delete_files(self, app_config):
        """删除原图+缩略图（接收配置，不依赖current_app）"""
        # 删除原图
        if self.filename:
            photo_path = os.path.join(
                app_config['PHOTO_FOLDER'], self.category, self.filename
            )
            if os.path.exists(photo_path):
                try:
                    os.remove(photo_path)
                except Exception as e:
                    error_msg = f'删除原图失败（{photo_path}）：{str(e)}'
                    logger.error(error_msg)

        # 删除缩略图
        if self.thumbnail:
            thumb_path = os.path.join(
                app_config['THUMBNAIL_FOLDER'], self.category, self.thumbnail
            )
            if os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception as e:
                    error_msg = f'删除缩略图失败（{thumb_path}）：{str(e)}'
                    logger.error(error_msg)