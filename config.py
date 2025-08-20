import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # 应用程序的密钥，用于会话管理、表单验证等安全相关功能
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here'

    # 数据库连接URI，指定数据库的类型和位置
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'app.db')

    # 禁用SQLAlchemy的修改跟踪功能，以提高性能
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 上传文件的最大大小限制
    MAX_CONTENT_LENGTH = 40 * 1024 * 1024 

    # 上传文件的保存目录，设置为项目根目录下的uploads文件夹
    UPLOAD_FOLDER = os.path.join(basedir, 'uploads')

    # 缩略图的保存目录，设置为uploads文件夹下的thumbnails子文件夹
    THUMBNAIL_FOLDER = os.path.join(basedir, 'uploads', 'thumbnails')

    # 允许上传的文件扩展名集合
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

    # JWT访问令牌的过期时间，此处设置为30天
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(days=30)
    
    # 网络基础路径，作为所有URL的根路径
    BASE_URL = os.environ.get('BASE_URL') or 'http://localhost:5000'

    # 上传文件的网络访问路径，基于基础URL构建
    UPLOADS_URL = f"{BASE_URL}/uploads"

    # 缩略图的网络访问路径
    THUMBNAILS_URL = f"{UPLOADS_URL}/thumbnails"

    # API的网络访问路径
    API_BASE_URL = f"{BASE_URL}/api"

    # 静态文件目录配置（指向项目根目录下的static文件夹）
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
