import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    # 数据库名：photo_data.db（完全由photo_processing.py控制）
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'photo_data.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB

    # 文件夹配置（不变）
    PHOTO_FOLDER = os.path.join(basedir, 'photo')
    THUMBNAIL_FOLDER = os.path.join(basedir, 'photo', 'thumbnails')
    STATIC_FOLDER = os.path.join(basedir, 'static')

    # 支持的图片格式（不变）
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    @staticmethod
    def init_app(app):
        """创建基础文件夹（不变）"""
        if not os.path.exists(Config.PHOTO_FOLDER):
            os.makedirs(Config.PHOTO_FOLDER)
        if not os.path.exists(Config.THUMBNAIL_FOLDER):
            os.makedirs(Config.THUMBNAIL_FOLDER)
        if not os.path.exists(Config.STATIC_FOLDER):
            os.makedirs(Config.STATIC_FOLDER)
