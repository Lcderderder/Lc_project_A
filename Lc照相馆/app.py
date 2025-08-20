from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from datetime import datetime
import os
from werkzeug.utils import secure_filename

from config import Config
from models import db, Photo
from utils import save_photo, allowed_file

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    
    # 初始化扩展
    db.init_app(app)
    CORS(app)
    
    # 确保上传目录存在
    Config.init_app(app)
    
    # 创建数据库表
    with app.app_context():
        db.create_all()
    
    return app

app = create_app()

# 静态文件路由 - 提供上传的照片
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/uploads/thumbnails/<filename>')
def uploaded_thumbnail(filename):
    return send_from_directory(app.config['THUMBNAIL_FOLDER'], filename)

# API路由
@app.route('/api/photos', methods=['GET'])
def get_photos():
    # 获取查询参数
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    year = request.args.get('year', type=int)
    category = request.args.get('category', type=str)
    
    # 构建查询
    query = Photo.query
    
    if year:
        start_date = datetime(year, 9, 1)  # 9月是学年开始
        end_date = datetime(year + 1, 6, 30)  # 次年6月是学年结束
        query = query.filter(Photo.date_taken.between(start_date, end_date))
    
    if category and category != '全部':
        query = query.filter(Photo.category == category)
    
    # 按时间倒序排列（最新的在前面）
    query = query.order_by(Photo.date_taken.desc())
    
    # 分页
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    photos = pagination.items
    
    return jsonify({
        'photos': [photo.to_dict() for photo in photos],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@app.route('/api/photos/<int:photo_id>', methods=['GET'])
def get_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    return jsonify(photo.to_dict())

@app.route('/api/photos', methods=['POST'])
def upload_photo():
    # 检查是否有文件部分
    if 'photo' not in request.files:
        return jsonify({'error': '没有文件部分'}), 400
    
    file = request.files['photo']
    
    # 如果用户没有选择文件
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400
    
    # 验证和处理文件
    filename, thumbnail = save_photo(file)
    if not filename:
        return jsonify({'error': '不支持的文件类型'}), 400
    
    # 获取表单数据
    title = request.form.get('title', '未命名照片')
    description = request.form.get('description', '')
    date_taken_str = request.form.get('date_taken')
    category = request.form.get('category', '其他')
    
    # 解析日期
    try:
        date_taken = datetime.fromisoformat(date_taken_str) if date_taken_str else datetime.utcnow()
    except ValueError:
        date_taken = datetime.utcnow()
    
    # 创建照片记录
    photo = Photo(
        title=title,
        description=description,
        filename=filename,
        thumbnail=thumbnail,
        date_taken=date_taken,
        category=category
    )
    
    db.session.add(photo)
    db.session.commit()
    
    return jsonify({
        'message': '照片上传成功',
        'photo': photo.to_dict()
    }), 201

@app.route('/api/photos/<int:photo_id>', methods=['PUT'])
def update_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    
    # 获取JSON数据
    data = request.get_json()
    
    if not data:
        return jsonify({'error': '没有提供数据'}), 400
    
    # 更新字段
    if 'title' in data:
        photo.title = data['title']
    if 'description' in data:
        photo.description = data['description']
    if 'date_taken' in data:
        try:
            photo.date_taken = datetime.fromisoformat(data['date_taken'])
        except ValueError:
            return jsonify({'error': '无效的日期格式'}), 400
    if 'category' in data:
        photo.category = data['category']
    
    db.session.commit()
    
    return jsonify({
        'message': '照片更新成功',
        'photo': photo.to_dict()
    })

@app.route('/api/photos/<int:photo_id>', methods=['DELETE'])
def delete_photo(photo_id):
    photo = Photo.query.get_or_404(photo_id)
    
    # 删除文件
    photo.delete_files()
    
    # 删除数据库记录
    db.session.delete(photo)
    db.session.commit()
    
    return jsonify({'message': '照片删除成功'})

# 错误处理
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': '资源未找到'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': '服务器内部错误'}), 500

if __name__ == '__main__':
    app.run(debug=True)