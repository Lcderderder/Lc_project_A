import os
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_wtf.csrf import CSRFProtect
from threading import Lock
from models import db, Photo
from config import Config
import photo_processing

# 全局状态控制
db_lock = Lock()  # 数据库操作锁
is_scanning = Lock()  # 扫描状态锁（通过acquire/release判断是否扫描中）

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.init_app(app)

    # 初始化扩展
    db.init_app(app)
    CSRFProtect(app)  # 启用CSRF保护

    # 创建数据库表
    with app.app_context():
        db.create_all()

    # ------------------------------
    # 路由定义
    # ------------------------------
    @app.route('/')
    def index():
        """首页返回前端页面"""
        return send_from_directory(app.config['STATIC_FOLDER'], 'Lc照相馆.html')

    @app.route('/photo/<category>/<filename>')
    def photo_file(category, filename):
        """访问原图"""
        # 验证分类目录合法性
        category_path = os.path.join(app.config['PHOTO_FOLDER'], category)
        if not os.path.isdir(category_path):
            return jsonify({'error': '无效的分类'}), 404
        # 验证文件类型
        if not photo_processing.allowed_file(filename):
            return jsonify({'error': '不支持的文件类型'}), 400
        return send_from_directory(category_path, filename)

    @app.route('/photo/thumbnails/<category>/<filename>')
    def thumbnail_file(category, filename):
        """访问缩略图"""
        # 验证分类目录合法性
        thumb_category_path = os.path.join(app.config['THUMBNAIL_FOLDER'], category)
        if not os.path.isdir(thumb_category_path):
            return jsonify({'error': '无效的分类'}), 404
        # 验证文件类型
        if not photo_processing.allowed_file(filename):
            return jsonify({'error': '不支持的文件类型'}), 400
        return send_from_directory(thumb_category_path, filename)

    @app.route('/api/photos', methods=['GET'])
    def get_photos():
        """获取照片列表（支持分类筛选和分页）"""
        if is_scanning.locked():
            return jsonify({'error': '数据库正在更新（扫描照片），暂时无法获取照片'}), 503

        # 基础查询
        query = Photo.query
        
        # 按分类筛选
        category = request.args.get('category')
        if category and category != 'all':  # 当category为空时不筛选，返回所有照片
            query = query.filter_by(category=category)
        
        # 分页参数
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)
        
        # 获取所有符合条件的照片
        photos = query.all()
        
        # 按文件名中的数字排序
        def extract_numeric(filename):
            base_name = os.path.splitext(filename)[0]
            numeric_part = ''.join(filter(str.isdigit, base_name))
            return int(numeric_part) if numeric_part else float('inf')  # 无数字放最后
        photos.sort(key=lambda x: extract_numeric(x.filename))
        
        # 计算分页
        total_photos = len(photos)
        total_pages = (total_photos + per_page - 1) // per_page
        page = max(1, min(page, total_pages)) if total_pages > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        current_photos = photos[start_idx:end_idx]
        
        return jsonify({
            'photos': [photo.to_dict() for photo in current_photos],
            'total': total_photos,
            'pages': total_pages,
            'current_page': page,
            'per_page': per_page
        })

    @app.route('/api/categories', methods=['GET'])
    def get_categories():
        """获取所有分类"""
        categories = db.session.query(Photo.category).distinct().all()
        return jsonify({
            'categories': [c[0] for c in categories]  # 仅返回实际分类
        })

    @app.route('/api/health', methods=['GET'])
    def health_check():
        """系统健康检查"""
        scan_finished = not is_scanning.locked()
        photo_count = Photo.query.count()
        return jsonify({
            'status': 'healthy',
            'scan_finished': scan_finished,
            'db_ready': True,
            'message': f"共{photo_count}张照片"
        })

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': '资源未找到'}), 404

    return app

# 自动扫描逻辑
def auto_scan_after_start(app):
    """后端启动后延迟执行自动扫描"""
    time.sleep(app.config['AUTO_SCAN_DELAY'])
    with app.app_context():
        if db_lock.acquire(blocking=False):
            try:
                is_scanning.acquire()  # 标记扫描中
                app.logger.info("后端启动完成，自动触发扫描（已加锁，禁止API访问）...")
                scan_result = photo_processing.scan_photo_folder(app)
                app.logger.info(f"自动扫描结果: {scan_result['message']}")
            except Exception as e:
                app.logger.error(f"自动扫描失败: {str(e)}")
            finally:
                is_scanning.release()  # 结束扫描标记
                db_lock.release()
                app.logger.info("数据库锁已释放，API可正常访问")
        else:
            app.logger.warning("获取数据库锁失败，扫描已在进行中")

if __name__ == '__main__':
    app = create_app()
    
    # 启动时在后台线程执行自动扫描
    import threading
    threading.Thread(target=auto_scan_after_start, args=(app,), daemon=True).start()
    app.run(host='0.0.0.0', port=5000, debug=False)
