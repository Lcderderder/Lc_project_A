import os
import time
import threading
import signal
import sys
import logging
from flask import Flask, request, jsonify, send_from_directory, current_app
from flask_wtf.csrf import CSRFProtect
from models import db, Photo
from config import Config
from PIL import Image

# 全局状态控制
db_lock = threading.Lock()
is_scanning_event = threading.Event()
is_scanning_event.set()  # 初始状态：扫描完成
server_running = True  # 服务器运行状态标记
scan_progress = {"total": 0, "processed": 0}  # 扫描进度


# 允许的图片文件后缀（与config一致）
def allowed_file(filename):
    """检查文件是否为支持的图片类型"""
    if not filename or '..' in filename or filename.startswith(('.', '~')):
        return False

    # 安全地获取文件扩展名
    if '.' not in filename:
        return False

    # 防止路径遍历攻击
    if '/' in filename or '\\' in filename:
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


def count_total_photos(app):
    """统计照片总数用于进度显示"""
    photo_root = app.config['PHOTO_FOLDER']
    total_count = 0

    try:
        all_items = os.listdir(photo_root)
    except (FileNotFoundError, PermissionError) as e:
        app.logger.error(f"无法访问照片根目录: {photo_root} - {str(e)}")
        return 0

    # 遍历photo文件夹下的所有子目录
    for item in all_items:
        item_path = os.path.join(photo_root, item)

        # 跳过非目录、隐藏文件和thumbnails目录
        if (not os.path.isdir(item_path) or
                item.startswith(('.', '~'))
                ):
            continue

        try:
            category_files = os.listdir(item_path)
        except (PermissionError, NotADirectoryError) as e:
            app.logger.error(f"无法访问分类目录 '{item_path}': {e}")
            continue

        # 统计分类目录下的有效图片文件
        for filename in category_files:
            file_path = os.path.join(item_path, filename)

            # 跳过隐藏文件和目录，只处理文件
            if (filename.startswith(('.', '~')) or not os.path.isfile(file_path)):
                continue

            # 只统计允许的图片文件
            if allowed_file(filename):
                total_count += 1

    return total_count


def scan_photo_folder(app):
    """扫描照片目录，生成缩略图并更新数据库"""
    from models import db, Photo

    logger = app.logger

    photo_root = app.config['PHOTO_FOLDER']
    thumbnail_root = app.config['THUMBNAIL_FOLDER']
    new_count = 0
    update_count = 0
    error_count = 0

    # 确保缩略图根目录存在
    os.makedirs(thumbnail_root, exist_ok=True)

    # 先统计照片总数
    global scan_progress
    scan_progress["total"] = count_total_photos(app)
    scan_progress["processed"] = 0
    logger.info(f"开始扫描，共发现 {scan_progress['total']} 张照片需要处理")

    try:
        all_items = os.listdir(photo_root)
    except (FileNotFoundError, PermissionError) as e:
        logger.error(f"无法访问照片根目录: {photo_root} - {str(e)}")
        return {"message": f"错误：无法访问照片根目录 '{photo_root}'", "new": 0, "updated": 0, "errors": 1}

    # 使用生成器表达式和分批处理来减少内存占用
    existing_photos_map = {}
    batch_size = 1000
    offset = 0

    while True:
        batch = Photo.query.offset(offset).limit(batch_size).all()
        if not batch:
            break

        for photo in batch:
            key = f"{photo.category}/{photo.filename}"
            existing_photos_map[key] = photo

        offset += batch_size
        # 释放内存
        del batch

    # 遍历photo文件夹下的所有子目录
    for item in all_items:
        item_path = os.path.join(photo_root, item)

        # 跳过非目录、隐藏文件和thumbnails目录
        if (not os.path.isdir(item_path) or
                item.startswith(('.', '~')) or
                item == 'thumbnails'):
            continue

        category = item
        logger.info(f"开始扫描分类: {category}")

        # 确保分类缩略图目录存在
        category_thumb_dir = os.path.join(thumbnail_root, category)
        os.makedirs(category_thumb_dir, exist_ok=True)

        try:
            category_files = os.listdir(item_path)
        except (PermissionError, NotADirectoryError) as e:
            logger.error(f"无法访问分类目录 '{item_path}': {e}")
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
                logger.debug(f"跳过不支持的文件类型: {filename}")
                continue

            # 更新进度
            scan_progress["processed"] += 1

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
                logger.info(f"缩略图不存在，将生成: {thumbnail_path}")
            else:
                try:
                    orig_mtime = os.path.getmtime(file_path)
                    thumb_mtime = os.path.getmtime(thumbnail_path)
                    if orig_mtime > thumb_mtime:
                        need_generate_thumbnail = True
                        logger.info(f"原图已更新，重新生成缩略图: {filename}")
                except OSError as e:
                    logger.error(f"无法获取文件修改时间: {file_path} 或 {thumbnail_path}, {e}")
                    need_generate_thumbnail = True

            if need_generate_thumbnail:
                if create_thumbnail(file_path, thumbnail_path):
                    thumbnail_generated = True
                    logger.info(f"已生成/更新缩略图: {thumbnail_path}")
                else:
                    error_count += 1
                    logger.error(f"生成缩略图失败，跳过文件: {file_path}")
                    continue

            if existing_photo:
                # 如果缩略图是新生成的，更新数据库记录
                if thumbnail_generated:
                    existing_photo.thumbnail = filename
                    update_count += 1
                    logger.debug(f"更新数据库记录: {category}/{filename}")
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
                logger.info(f"新增数据库记录: {category}/{filename}")
                # 添加到映射中避免重复添加
                existing_photos_map[photo_key] = new_photo

    try:
        db.session.commit()
        result_msg = f"扫描完成，新增 {new_count} 张照片，更新 {update_count} 张照片记录，遇到 {error_count} 个错误"
        return {
            "message": result_msg,
            "new": new_count,
            "updated": update_count,
            "errors": error_count
        }
    except Exception as e:
        db.session.rollback()
        logger.error(f"数据库提交失败: {str(e)}")
        return {
            "message": f"扫描失败（数据库错误）: {str(e)}",
            "new": 0,
            "updated": 0,
            "errors": error_count + 1
        }


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.init_app(app)

    # <<< 日志到位：清理默认 handler，改成 stdout + INFO（不带时间戳） >>>
    app.logger.handlers.clear()
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(logging.INFO)
    h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    app.logger.addHandler(h)
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False  # 避免向 root logger 传播导致重复/覆盖

    # 统一 werkzeug 的日志到同一 handler，并减少 HTTP 噪音
    wlog = logging.getLogger("werkzeug")
    wlog.handlers.clear()
    wlog.addHandler(h)
    wlog.setLevel(logging.WARNING)
    wlog.propagate = False

    # 初始化扩展
    db.init_app(app)
    CSRFProtect(app)

    # 创建数据库表
    with app.app_context():
        try:
            app.logger.info("数据库初始化...")
            db.drop_all()   # 删除所有表
            db.create_all()   # 重新建表
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
        if not allowed_file(filename):
            return jsonify({'error': '不支持的文件类型'}), 400

        response = send_from_directory(category_path, filename)
        # 设置缓存头 - 图片资源可缓存1小时
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response

    @app.route('/thumbnails/<category>/<filename>')
    def thumbnail_file(category, filename):
        # 安全检查：防止路径遍历攻击
        if '..' in category or '..' in filename or '/' in category or '/' in filename:
            return jsonify({'error': '无效的路径'}), 400

        thumb_category_path = os.path.join(app.config['THUMBNAIL_FOLDER'], category)
        if not os.path.isdir(thumb_category_path):
            return jsonify({'error': '无效的分类'}), 404
        if not allowed_file(filename):
            return jsonify({'error': '不支持的文件类型'}), 400

        # 进一步验证路径在预期范围内
        real_path = os.path.realpath(os.path.join(thumb_category_path, filename))
        if not real_path.startswith(os.path.realpath(app.config['THUMBNAIL_FOLDER'])):
            return jsonify({'error': '访问越界'}), 403

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
            photos = query.order_by(Photo.filename).all()
        except Exception as e:
            app.logger.error(f"照片查询失败: {str(e)}", exc_info=True)
            return jsonify({
                'error': '获取照片失败',
                'details': str(e) if app.debug else '请查看服务器日志'
            }), 500

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

        # 返回扫描进度信息
        return jsonify({
            'status': 'healthy' if db_ready else 'unhealthy',
            'scan_finished': scan_finished,
            'db_ready': db_ready,
            'message': status_message,
            'scan_progress': scan_progress if not scan_finished else {}
        })

    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': '资源未找到'}), 404

    @app.errorhandler(500)
    def server_error(error):
        app.logger.error(f"服务器内部错误: {str(error)}")
        return jsonify({'error': '服务器内部错误'}), 500

    return app


# —— 优雅关闭：用闭包持有 app，避免使用 current_app —— #
def make_handle_termination(app):
    def _handle(signum, frame):
        logger = app.logger
        logger.info(f"收到终止信号 {signum}，正在优雅关闭...")

        global server_running
        server_running = False

        # 等待扫描完成（最多10秒）
        if not is_scanning_event.is_set():
            logger.info("等待当前扫描完成...")
            is_scanning_event.wait(10)

        # 释放数据库锁
        if db_lock.locked():
            logger.info("释放数据库锁...")
            try:
                db_lock.release()
            except Exception as e:
                logger.warning(f"释放数据库锁失败: {str(e)}")

        # 关闭数据库连接（进入 app 上下文更安全）
        with app.app_context():
            logger.info("关闭数据库连接...")
            db.session.remove()
            db.engine.dispose()

        logger.info("服务已关闭")
        sys.exit(0)

    return _handle


# 自动扫描逻辑 - 移除延迟，立即开始扫描
def auto_scan_after_start(app):
    try:
        with app.app_context():
            if db_lock.acquire(blocking=False):
                try:
                    is_scanning_event.clear()
                    app.logger.info("后端启动完成，立即开始扫描照片...")

                    scan_result = scan_photo_folder(app)
                    app.logger.info(f"扫描结果: {scan_result['message']}")

                except Exception as e:
                    app.logger.error(f"扫描失败: {str(e)}")
                    # 记录详细错误信息
                    import traceback
                    app.logger.error(f"详细错误: {traceback.format_exc()}")
                finally:
                    is_scanning_event.set()
                    db_lock.release()
                    app.logger.info("数据库锁已释放，API可正常访问")
            else:
                app.logger.warning("获取数据库锁失败，扫描已在进行中")
    except Exception as e:
        app.logger.error(f"扫描线程异常: {str(e)}")
        # 确保异常情况下也能设置事件和释放锁
        is_scanning_event.set()
        if db_lock.locked():
            try:
                db_lock.release()
            except Exception:
                pass


if __name__ == '__main__':
    app = create_app()

    # 注册信号处理器（跨平台）
    term_handler = make_handle_termination(app)
    try:
        if sys.platform == "win32":
            # Windows系统信号处理
            try:
                import win32api

                def handle_win32_terminate(sig, func=None):
                    term_handler(sig, None)

                try:
                    win32api.SetConsoleCtrlHandler(handle_win32_terminate, True)
                except Exception as e:
                    app.logger.warning(f"Windows信号处理初始化警告: {str(e)}")
            except Exception as e:
                app.logger.warning(f"Windows信号模块不可用: {str(e)}")
        else:
            # Unix/Linux系统信号处理
            signal.signal(signal.SIGTERM, term_handler)
            signal.signal(signal.SIGINT, term_handler)
    except Exception as e:
        app.logger.error(f"信号处理初始化失败: {str(e)}")

    # 启动自动扫描线程 - 立即开始扫描
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
        app.logger.info("服务器已启动在 http://0.0.0.0:5000")

        # 保持主线程运行，直到收到终止信号
        while server_running:
            time.sleep(1)

        # 关闭服务器
        server.shutdown()
        server.join()

    except Exception as e:
        app.logger.error(f"服务启动失败: {str(e)}")
        sys.exit(1)
