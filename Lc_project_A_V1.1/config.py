import os
basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    # 基础URL配置
    BASE_URL = "http://localhost:5000/"
    API_URL = f"{BASE_URL}api/"

    # 安全配置
    SECRET_KEY = os.environ.get('SECRET_KEY') or '$T,#KMK.+{Od:pTcfV{5,H~[.1XQh|X?'
    if not SECRET_KEY:
        raise ValueError("未设置SECRET_KEY环境变量")

    # 数据库配置
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'photo_data.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # 文件上传限制（40MB）
    MAX_CONTENT_LENGTH = 40 * 1024 * 1024

    # 文件夹路径配置
    PHOTO_FOLDER = os.path.join(basedir, 'photo')         # 原图根目录
    THUMBNAIL_FOLDER = os.path.join(basedir, 'thumbnails')  # 缩略图根目录
    STATIC_FOLDER = os.path.join(basedir, 'static')       # 静态文件目录

    # 支持的图片格式
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp'}

    # 自动扫描延迟（秒）
    AUTO_SCAN_DELAY = 2

    # 缩略图尺寸（宽，高）
    THUMBNAIL_MAX_SIZE = (500, 500)

    @staticmethod
    def init_app(app):
        """初始化必要文件夹"""
        required_folders = [
            Config.PHOTO_FOLDER,
            Config.THUMBNAIL_FOLDER,
            Config.STATIC_FOLDER
        ]
        for folder in required_folders:
            if not os.path.exists(folder):
                try:
                    os.makedirs(folder, exist_ok=True)
                    app.logger.info(f"已创建文件夹: {folder}")
                except OSError as e:
                    app.logger.error(f"无法创建文件夹 {folder}: {str(e)}")
                    raise