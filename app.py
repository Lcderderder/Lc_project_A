from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import os
import threading
import time
from config import Config
from models import db, Photo
import photo_processing
from logger import setup_logger

# 初始化日志器
logger = setup_logger(__name__)

# ------------------------------
# 核心：创建全局数据库锁，确保同一时间只有一个线程访问数据库
# ------------------------------
db_lock = threading.Lock()
is_scanning = False  # 标记是否正在扫描（避免重复触发）

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # 初始化扩展
    db.init_app(app)
    # 修复跨域：允许所有来源
    CORS(app, resources={
        r"/api/*": {
            "origins": "*",
            "methods": ["GET", "POST", "PUT", "DELETE"],
            "allow_headers": ["Content-Type"],
            "supports_credentials": True
        }
    })
    
    # 确保基础文件夹存在
    Config.init_app(app)
    
    # 后端启动后自动扫描（加锁，避免并发）
    def auto_scan_after_start():
        global is_scanning
        time.sleep(2)  # 延迟2秒，确保Flask服务就绪
        with app.app_context():
            # 加锁：确保扫描期间其他线程无法访问数据库
            if db_lock.acquire(blocking=False):  # 非阻塞获取锁，避免死锁
                try:
                    is_scanning = True
                    print("="*50)
                    print("后端启动完成，自动触发扫描（已加锁，禁止API访问）...")
                    print("="*50)
                    scan_result = photo_processing.scan_photo_folder()
                    print(f"自动扫描结果：{scan_result['message']}")
                finally:
                    is_scanning = False
                    db_lock.release()  # 无论成功失败，都释放锁
                    print("数据库锁已释放，API可正常访问")
            else:
                print("获取数据库锁失败，扫描已在进行中")

    # 启动自动扫描线程（守护线程，随主进程退出）
    auto_scan_thread = threading.Thread(target=auto_scan_after_start, daemon=True)
    auto_scan_thread.start()
    
    return app

app = create_app()

# ------------------------------
# 静态文件+图片路由（不变）
# ------------------------------
@app.route('/static/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.config['STATIC_FOLDER'], filename)

@app.route('/')
def index():
    return send_from_directory(app.config['STATIC_FOLDER'], 'Lc照相馆.html')

@app.route('/photo/<category>/<filename>')
def photo_file(category, filename):
    return send_from_directory(os.path.join(app.config['PHOTO_FOLDER'], category), filename)

@app.route('/photo/thumbnails/<category>/<filename>')
def photo_thumbnail(category, filename):
    thumb_folder = os.path.join(app.config['THUMBNAIL_FOLDER'], category)
    print(f"访问缩略图：{thumb_folder}/{filename}")  
    return send_from_directory(thumb_folder, filename)# ------------------------------

# ------------------------------
@app.route('/api/health', methods=['GET'])
def api_health():
    """健康检查：返回后端状态+扫描状态+数据库状态"""
    global is_scanning
    health_data = {
        "backend_running": True,
        "db_ready": False,
        "scan_finished": not is_scanning,
        "message": "后端运行中，数据库更新中（扫描未完成），暂时无法访问"
    }

    # 若未扫描，尝试检查数据库（加锁访问）
    if not is_scanning:
        if db_lock.acquire(blocking=False):
            try:
                photo_count = Photo.query.count()
                health_data["db_ready"] = True
                health_data["message"] = f"后端正常运行，数据库就绪（共{photo_count}张照片）"
            except Exception:
                health_data["db_ready"] = False
                health_data["message"] = "后端运行中，数据库未初始化（首次扫描未完成）"
            finally:
                db_lock.release()

    return jsonify(health_data), 200

@app.route('/api/categories', methods=['GET'])
def get_categories():
    """获取分类（基于文件夹，不依赖数据库，无需锁）"""
    categories = [
        f for f in os.listdir(app.config['PHOTO_FOLDER']) 
        if os.path.isdir(os.path.join(app.config['PHOTO_FOLDER'], f)) and f != 'thumbnails'
    ]
    return jsonify(categories)

@app.route('/api/photos', methods=['GET'])
def get_photos():
    """获取照片：扫描中拒绝访问，否则加锁读取"""
    global is_scanning
    # 扫描中，直接返回提示
    if is_scanning:
        return jsonify({
            'error': '数据库正在更新（扫描照片），请10秒后再试',
            'photos': [], 'total': 0, 'pages': 0, 'current_page': request.args.get('page', 1)
        }), 503  # 503：服务暂时不可用

    # 加锁读取数据，避免与其他操作冲突
    if db_lock.acquire(blocking=True, timeout=5):  # 最多等待5秒，超时返回错误
        try:
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 12, type=int)
            category = request.args.get('category', type=str)

            query = Photo.query
            if category and category != 'all':
                query = query.filter(Photo.category == category)
            
            query = query.order_by(Photo.id.desc())
            pagination = query.paginate(page=page, per_page=per_page, error_out=False)

            return jsonify({
                'photos': [p.to_dict() for p in pagination.items],
                'total': pagination.total,
                'pages': pagination.pages,
                'current_page': page
            })
        except Exception as e:
            error_msg = f'读取数据失败：{str(e)}'
            logger.error(error_msg)
            return jsonify({
                'error': error_msg,
                'photos': [], 'total': 0, 'pages': 0, 'current_page': page
            }), 500
        finally:
            db_lock.release()
    else:
        return jsonify({
            'error': '数据库繁忙，请稍后再试',
            'photos': [], 'total': 0, 'pages': 0, 'current_page': request.args.get('page', 1)
        }), 503

@app.route('/api/photos/<int:photo_id>', methods=['DELETE'])
def delete_photo(photo_id):
    """删除照片：扫描中拒绝访问，否则加锁操作"""
    global is_scanning
    if is_scanning:
        return jsonify({'error': '数据库正在更新（扫描照片），暂时无法删除'}), 503

    if db_lock.acquire(blocking=True, timeout=5):
        try:
            photo = Photo.query.get_or_404(photo_id)
            photo.delete_files(app.config)
            db.session.delete(photo)
            db.session.commit()
            return jsonify({'message': '删除成功'})
        except Exception as e:
            db.session.rollback()
            error_msg = f'删除照片失败（ID: {photo_id}）：{str(e)}'
            logger.error(error_msg)
            return jsonify({'error': str(e)}), 500
        finally:
            db_lock.release()
    else:
        return jsonify({'error': '数据库繁忙，请稍后再试'}), 503

# ------------------------------
# 错误处理（不变）
# ------------------------------
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '资源未找到'}), 404

@app.errorhandler(500)
def internal_error(error):
    error_msg = f'服务器内部错误：{str(error)}'
    logger.error(error_msg)
    return jsonify({'error': '服务器内部错误'}), 500

if __name__ == '__main__':
    app.run(debug=True)
