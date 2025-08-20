import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')
    THUMBNAIL_FOLDER = os.path.join(basedir, 'uploads', 'thumbnails')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=30)
    
    # 新增：静态文件目录配置（指向项目根目录下的static文件夹）
    STATIC_FOLDER = os.path.join(basedir, 'static')
    
    @staticmethod
    def init_app(app):
        # 确保上传目录存在
        if not os.path.exists(Config.UPLOAD_FOLDER):
            os.makedirs(Config.UPLOAD_FOLDER)
        if not os.path.exists(Config.THUMBNAIL_FOLDER):
            os.makedirs(Config.THUMBNAIL_FOLDER)
        # 新增：确保静态文件夹存在（避免目录不存在报错）
        if not os.path.exists(Config.STATIC_FOLDER):
            os.makedirs(Config.STATIC_FOLDER)
