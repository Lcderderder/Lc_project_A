from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

db = SQLAlchemy()

class Photo(db.Model):
    __tablename__ = 'photos'
    
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    filename = db.Column(db.String(100), nullable=False)
    thumbnail = db.Column(db.String(100))
    date_taken = db.Column(db.DateTime, nullable=False)
    category = db.Column(db.String(50), nullable=False)
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'filename': self.filename,
            'thumbnail': self.thumbnail,
            'date_taken': self.date_taken.isoformat(),
            'category': self.category,
            'upload_date': self.upload_date.isoformat()
        }
    
    def delete_files(self):
        # 删除实际的文件
        if self.filename:
            file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], self.filename)
            if os.path.exists(file_path):
                os.remove(file_path)
        
        if self.thumbnail:
            thumb_path = os.path.join(current_app.config['THUMBNAIL_FOLDER'], self.thumbnail)
            if os.path.exists(thumb_path):
                os.remove(thumb_path)