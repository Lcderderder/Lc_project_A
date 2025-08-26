import os
import time
import threading
import signal
import sys
from flask import Flask, request, jsonify, send_from_directory
from flask_wtf.csrf import CSRFProtect
from models import db, Photo
from config import Config
import photo_processing

# 全局状态控制
db_lock = threading.Lock()
is_scanning_event = threading.Event()
is_scanning_event.set()  # 初始状态：扫描完成
server_running = True  # 服务器运行状态标记

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.init_app(app)

    # 初始化扩展
    db.init_app(app)
    CSRFProtect(app)

    # 创建数据库表
    with app.app_context():
        try:
            db.create_all()
            app.logger.info("数据库表创建成功")
        except Exception as e:
            app.logger.error(f"数据库表创建失败: {str(e)}")

    # ------------------------------
    # 路由定义
    # ------------------------------
    @app.route('/')
    def index():
        return send_from_directory(app.config['STATIC_FOLDER'], 'Lc照相馆.html')

    @app.route('/photo/<category>/<filename>')
    def photo_file(category, filename):
        category_path = os.path.join(app.config['PHOTO_FOLDER'], category)
        if not os.path.isdir(category_path):
            return jsonify({'error': '无效的分类'}), 404
        if not photo_processing.allowed_file(filename):
            return jsonify({'error': '不支持的文件类型'}), 400
        return send_from_directory(category_path, filename)

    @app.route('/photo/thumbnails/<category>/<filename>')
    def thumbnail_file(category, filename):
        thumb_category_path = os.path.join(app.config['THUMBNAIL_FOLDER'], category)
        if not os.path.isdir(thumb_category_path):
            return jsonify({'error': '无效的分类'}), 404
        if not photo_processing.allowed_file(filename):
            return jsonify({'error': '不支持的文件类型'}), 400
        return send_from_directory(thumb_category_path, filename)

    @app.route('/api/photos', methods=['GET'])
    def get_photos():
        if db_lock.locked() or not is_scanning_event.is_set():
            return jsonify({'error': '数据库正在更新（扫描照片），暂时无法获取照片'}), 503

        query = Photo.query
        
        category = request.args.get('category')
        if category and category != 'all':
            query = query.filter_by(category=category)
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 12, type=int)
        
        try:
            photos = query.all()
        except Exception as e:
            app.logger.error(f"照片查询失败: {str(e)}")
            return jsonify({'error': '获取照片失败'}), 500
        
        def extract_numeric(filename):
            base_name = os.path.splitext(filename)[0]
            numeric_part = ''.join(filter(str.isdigit, base_name))
            return int(numeric_part) if numeric_part else float('inf')
        photos.sort(key=lambda x: extract_numeric(x.filename))
        
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
        try:
            categories = db.session.query(Photo.category).distinct().all()
            return jsonify({
                'categories': [c[0] for c in categories if c[0]]
            })
        except Exception as e:
            app.logger.error(f"分类查询失败: {str(e)}")
            return jsonify({'error': '获取分类失败'}), 500

    @app.route('/api/health', methods=['GET'])
    def health_check():
        scan_finished = is_scanning_event.is_set()
        db_ready = False
        photo_count = 0
        status_message = "数据库未就绪"
        
        try:
            photo_count = Photo.query.count()
            db_ready = True
            status_message = f"共{photo_count}张照片"
        except Exception as e:
            app.logger.warning(f"数据库健康检查失败: {str(e)}")
        
        return jsonify({
            'status': 'healthy' if db_ready else 'unhealthy',
            'scan_finished': scan_finished,
            'db_ready': db_ready,
            'message': status_message
        })

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': '资源未找到'}), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.error(f"服务器内部错误: {str(error)}")
        return jsonify({'error': '服务器内部错误'}), 500

    return app

# 信号处理函数 - 优雅关闭
def handle_termination(signum, frame):
    global server_running
    app.logger.info(f"收到终止信号 {signum}，正在优雅关闭...")
    
    # 标记服务器为非运行状态
    server_running = False
    
    # 等待扫描完成
    if not is_scanning_event.is_set():
        app.logger.info("等待当前扫描完成...")
        # 最多等待10秒
        is_scanning_event.wait(10)
    
    # 释放数据库锁
    if db_lock.locked():
        app.logger.info("释放数据库锁...")
        try:
            db_lock.release()
        except Exception as e:
            app.logger.warning(f"释放数据库锁失败: {str(e)}")
    
    # 关闭数据库连接
    app.logger.info("关闭数据库连接...")
    db.session.remove()
    db.engine.dispose()
    
    app.logger.info("服务已关闭")
    sys.exit(0)

# 自动扫描逻辑
def auto_scan_after_start(app):
    time.sleep(app.config['AUTO_SCAN_DELAY'])
    with app.app_context():
        if db_lock.acquire(blocking=False):
            try:
                is_scanning_event.clear()
                app.logger.info("后端启动完成，自动触发扫描...")
                
                scan_result = photo_processing.scan_photo_folder(app)
                app.logger.info(f"自动扫描结果: {scan_result['message']}")
                
            except Exception as e:
                app.logger.error(f"自动扫描失败: {str(e)}")
            finally:
                is_scanning_event.set()
                db_lock.release()
                app.logger.info("数据库锁已释放，API可正常访问")
        else:
            app.logger.warning("获取数据库锁失败，扫描已在进行中")

if __name__ == '__main__':
    app = create_app()
    
    # 注册信号处理器（修复Windows兼容性问题）
    try:
        if sys.platform == "win32":
            # Windows系统信号处理 - 增加异常捕获
            import win32api
            def handle_win32_terminate(sig, func=None):
                handle_termination(sig, None)
            # 尝试设置控制台控制处理器
            try:
                win32api.SetConsoleCtrlHandler(handle_win32_terminate, True)
            except Exception as e:
                app.logger.warning(f"Windows信号处理初始化警告: {str(e)}")
        else:
            # Unix/Linux系统信号处理
            signal.signal(signal.SIGTERM, handle_termination)
            signal.signal(signal.SIGINT, handle_termination)
    except Exception as e:
        app.logger.error(f"信号处理初始化失败: {str(e)}")
    
    # 启动自动扫描线程
    scan_thread = threading.Thread(
        target=auto_scan_after_start, 
        args=(app,), 
        daemon=True
    )
    scan_thread.start()
    
    # 启动服务
    try:
        from werkzeug.serving import make_server
        
        # 使用自定义服务器以便控制
        class ServerThread(threading.Thread):
            def __init__(self):
                super().__init__()
                self.server = make_server('0.0.0.0', 5000, app)
                self.ctx = app.app_context()
                self.ctx.push()
                
            def run(self):
                app.logger.info('开始运行服务器...')
                self.server.serve_forever()
                
            def shutdown(self):
                self.server.shutdown()
        
        server = ServerThread()
        server.start()
        app.logger.info(f"服务器已启动在 http://0.0.0.0:5000")
        
        # 保持主线程运行，直到收到终止信号
        while server_running:
            time.sleep(1)
        
        # 关闭服务器
        server.shutdown()
        server.join()
        
    except Exception as e:
        app.logger.error(f"服务启动失败: {str(e)}")
        sys.exit(1)
