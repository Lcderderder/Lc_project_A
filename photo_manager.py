import sys
import os
import json
import subprocess
import time
from datetime import datetime
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QListWidget, QListWidgetItem, QLabel, QTextEdit, QLineEdit, 
                             QDateEdit, QComboBox, QFileDialog, QMessageBox, QSplitter,
                             QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget,
                             QGroupBox, QFormLayout, QProgressBar, QStatusBar, QSizePolicy,
                             QToolTip)
from PyQt5.QtCore import Qt, QDate, QSize, QThread, pyqtSignal, QCoreApplication, QPoint, QEvent
from PyQt5.QtGui import QPixmap, QIcon, QFont, QColor, QCloseEvent, QPalette
import requests
from PIL import Image
import io

# 修复导入问题
from flask import current_app

# ------------------------------
# 后端启动检测线程
# ------------------------------
class BackendCheckThread(QThread):
    check_result = pyqtSignal(bool, str)  

    def __init__(self, api_url):
        super().__init__()
        self.api_url = api_url
        self.running = True

    def run(self):
        for _ in range(10):
            if not self.running:
                break
            try:
                response = requests.get(self.api_url, timeout=1)
                if response.status_code == 200:
                    self.check_result.emit(True, "后端启动成功！API可正常访问")
                    return
            except requests.exceptions.ConnectionError:
                time.sleep(1)
            except Exception as e:
                self.check_result.emit(False, f"检测异常：{str(e)[:20]}")
                time.sleep(1)
        self.check_result.emit(False, "后端启动超时！请手动启动")

    def stop(self):
        self.running = False

# ------------------------------
# 主窗口类
# ------------------------------
class PhotoManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_base_url = "http://localhost:5000/api"
        self.current_photo_id = None
        self.photos = []
        self.backend_process = None  
        self.backend_check_thread = None  

        # 初始化UI
        self.initUI()

        # 窗口居中
        self.center_window()

        # 自动启动后端
        self.auto_start_backend()

    # ------------------------------
    # 初始化UI
    # ------------------------------
    def initUI(self):
        self.setWindowTitle('Lc照相馆管理系统 - 后台管理系统')
        self.setGeometry(100, 100, 1200, 800)
        if os.path.exists('camera_icon.png'):
            self.setWindowIcon(QIcon('camera_icon.png'))

        # 设置应用程序样式
        self.setApplicationStyle()

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        # 后端状态面板
        self.backend_status_panel = QWidget()
        self.backend_status_panel.setObjectName("BackendStatusPanel")
        self.backend_status_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.backend_status_panel.setFixedHeight(120)
        status_layout = QVBoxLayout(self.backend_status_panel)
        status_layout.setAlignment(Qt.AlignCenter)

        self.status_title = QLabel("后端服务状态")
        self.status_title.setFont(QFont("微软雅黑", 13, QFont.Bold))
        self.status_title.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.status_title)

        self.status_content = QLabel("初始化中...")
        self.status_content.setFont(QFont("微软雅黑", 14))
        self.status_content.setAlignment(Qt.AlignCenter)
        self.status_content.setStyleSheet("color: #ffc107;")
        status_layout.addWidget(self.status_content)

        self.manual_start_btn = QPushButton("手动启动后端")
        self.manual_start_btn.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                margin-top: 10px;
            }
            QPushButton:hover {
                background-color: #bb2d3b;
            }
        """)
        self.manual_start_btn.clicked.connect(self.manual_start_backend)
        self.manual_start_btn.hide()
        status_layout.addWidget(self.manual_start_btn)

        main_layout.addWidget(self.backend_status_panel)

        # 功能区分割器
        splitter = QSplitter(Qt.Horizontal)
        splitter.setSizes([400, 800])

        # 左侧部件
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(10, 10, 10, 10)
        left_layout.setSpacing(15)

        # 搜索分组
        search_group = QGroupBox("搜索和筛选")
        search_layout = QFormLayout(search_group)
        search_layout.setSpacing(10)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入关键词搜索...")
        self.search_input.textChanged.connect(self.filter_photos)
        search_layout.addRow("搜索:", self.search_input)

        self.category_filter = QComboBox()
        self.category_filter.addItems(["全部", "班级活动", "毕业照", "运动会", "课外活动", "校园风景", "其他"])
        self.category_filter.currentTextChanged.connect(self.filter_photos)
        search_layout.addRow("分类:", self.category_filter)

        self.year_filter = QComboBox()
        self.year_filter.addItems(["全部", "2022", "2023", "2024", "2025"])
        self.year_filter.currentTextChanged.connect(self.filter_photos)
        search_layout.addRow("年份:", self.year_filter)

        left_layout.addWidget(search_group)

        # 照片列表
        self.photo_list = QListWidget()
        self.photo_list.setIconSize(QSize(100, 100))
        self.photo_list.currentRowChanged.connect(self.show_photo_details)
        self.photo_list.setMinimumHeight(300)
        left_layout.addWidget(self.photo_list)

        # 左侧按钮
        button_layout = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新照片")
        self.refresh_btn.clicked.connect(self.load_photos)
        self.upload_btn = QPushButton("上传照片")
        self.upload_btn.clicked.connect(self.upload_photo)
        self.delete_btn = QPushButton("删除选中")
        self.delete_btn.clicked.connect(self.delete_photo)
        button_layout.addWidget(self.refresh_btn)
        button_layout.addWidget(self.upload_btn)
        button_layout.addWidget(self.delete_btn)
        left_layout.addLayout(button_layout)

        # 右侧部件
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(10, 10, 10, 10)
        right_layout.setSpacing(15)

        # 照片预览
        self.photo_preview = QLabel()
        self.photo_preview.setAlignment(Qt.AlignCenter)
        self.photo_preview.setStyleSheet("border: 1px solid #ccc; border-radius: 4px;")
        self.photo_preview.setMinimumSize(400, 300)
        self.photo_preview.setText("选择照片预览")
        right_layout.addWidget(self.photo_preview)

        # 详情分组
        details_group = QGroupBox("照片详情")
        details_layout = QFormLayout(details_group)
        details_layout.setSpacing(10)

        self.title_input = QLineEdit()
        details_layout.addRow("标题:", self.title_input)

        self.description_input = QTextEdit()
        self.description_input.setMaximumHeight(100)
        details_layout.addRow("描述:", self.description_input)

        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        details_layout.addRow("日期:", self.date_input)

        self.category_input = QComboBox()
        self.category_input.addItems(["班级活动", "毕业照", "运动会", "课外活动", "校园风景", "其他"])
        details_layout.addRow("分类:", self.category_input)

        self.save_btn = QPushButton("保存更改")
        self.save_btn.clicked.connect(self.save_photo_details)
        details_layout.addRow(self.save_btn)

        right_layout.addWidget(details_group)

        # 系统信息分组
        info_group = QGroupBox("系统信息")
        info_layout = QVBoxLayout(info_group)
        info_layout.setSpacing(10)

        self.photo_count_label = QLabel("照片总数: 0")
        self.photo_count_label.setFont(QFont("微软雅黑", 13))
        self.storage_info_label = QLabel("存储使用: 功能待实现")
        self.storage_info_label.setFont(QFont("微软雅黑", 13))
        self.api_status_label = QLabel("API状态: 待检测")
        self.api_status_label.setFont(QFont("微软雅黑", 13))
        info_layout.addWidget(self.photo_count_label)
        info_layout.addWidget(self.storage_info_label)
        info_layout.addWidget(self.api_status_label)

        right_layout.addWidget(info_group)
        right_layout.addStretch()

        # 添加到分割器
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        main_layout.addWidget(splitter)

        # 状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")

    def setApplicationStyle(self):
        """设置应用程序样式"""
        # 设置Fusion样式
        QApplication.setStyle("Fusion")

        app_font = QApplication.font()
        app_font.setPointSize(11)  # 增加默认字体大小
        QApplication.setFont(app_font)
        
        # 设置调色板
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(245, 245, 245))
        palette.setColor(QPalette.WindowText, Qt.black)
        palette.setColor(QPalette.Base, QColor(255, 255, 255))
        palette.setColor(QPalette.AlternateBase, QColor(240, 240, 240))
        palette.setColor(QPalette.Button, QColor(240, 240, 240))
        palette.setColor(QPalette.ButtonText, Qt.black)
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        QApplication.setPalette(palette)
        
        # 设置样式表
        style_sheet = """
            QMainWindow {
                background-color: #F5F5F5;
            }
            QWidget#BackendStatusPanel {
                background-color: #f8f9fa;
                border: 2px solid #dee2e6;
                border-radius: 12px;
                padding: 20px;
            }
            QPushButton {
                background-color: #0d6efd;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                margin: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #0b5ed7;
            }
            QLineEdit, QTextEdit, QDateEdit, QComboBox {
                background-color: white;
                border: 1px solid #ced4da;
                border-radius: 4px;
                padding: 6px;
                font-size: 12px;
            }
            QGroupBox {
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin-top: 12px;
                padding: 10px;
                font-weight: bold;
            }
            QListWidget {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: white;
                font-size: 12px;
            }
            QListWidget::item {
                padding: 6px;
            }
            QListWidget::item:selected {
                background-color: #0d6efd;
                color: white;
            }
            QSplitter::handle {
                background-color: #ced4da;
                width: 4px;
                height: 4px;
            }
            QLabel {
                font-size: 14px;  /* 增加所有标签的字体大小 */
            }
        """
        self.setStyleSheet(style_sheet)

    # ------------------------------
    # 窗口居中
    # ------------------------------
    def center_window(self):
        screen = QApplication.primaryScreen()
        screen_geometry = screen.availableGeometry()
        window_geometry = self.frameGeometry()
        center_point = screen_geometry.center()
        window_geometry.moveCenter(center_point)
        self.move(window_geometry.topLeft())

    # ------------------------------
    # 后端管理
    # ------------------------------
    def auto_start_backend(self):
        self.update_backend_status("后端自动启动中...", color="#ffc107")
        self.manual_start_btn.hide()

        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))
            app_path = os.path.join(project_dir, "app.py")
            if not os.path.exists(app_path):
                raise FileNotFoundError(f"未找到app.py（路径：{app_path}）")

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.backend_process = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )

            self.backend_check_thread = BackendCheckThread(f"{self.api_base_url}/photos")
            self.backend_check_thread.check_result.connect(self.on_backend_check_finish)
            self.backend_check_thread.start()

        except Exception as e:
            err_msg = f"自动启动失败：{str(e)[:30]}..."
            self.update_backend_status(err_msg, color="#dc3545")
            self.manual_start_btn.show()
            self.statusBar.showMessage(err_msg)

    def manual_start_backend(self):
        self.update_backend_status("手动启动后端中...", color="#ffc107")
        self.manual_start_btn.hide()

        try:
            if self.backend_process:
                self.backend_process.terminate()
                time.sleep(1)

            project_dir = os.path.dirname(os.path.abspath(__file__))
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.backend_process = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )

            if self.backend_check_thread:
                self.backend_check_thread.stop()
            self.backend_check_thread = BackendCheckThread(f"{self.api_base_url}/photos")
            self.backend_check_thread.check_result.connect(self.on_backend_check_finish)
            self.backend_check_thread.start()

        except Exception as e:
            err_msg = f"手动启动失败：{str(e)[:30]}..."
            self.update_backend_status(err_msg, color="#dc3545")
            self.manual_start_btn.show()
            self.statusBar.showMessage(err_msg)

    def on_backend_check_finish(self, is_success, msg):
        if is_success:
            self.update_backend_status(msg, color="#28a745")
            self.api_status_label.setText("API状态: 正常")
            self.api_status_label.setStyleSheet("color: green;")
            self.load_photos()
            self.statusBar.showMessage("后端服务正常运行")
        else:
            self.update_backend_status(msg, color="#dc3545")
            self.api_status_label.setText("API状态: 不可用")
            self.api_status_label.setStyleSheet("color: red;")
            self.manual_start_btn.show()
            self.statusBar.showMessage("后端服务不可用")

    def update_backend_status(self, content, color):
        self.status_content.setText(content)
        self.status_content.setStyleSheet(f"color: {color}; font-size: 12px;")

    # ------------------------------
    # 照片管理功能
    # ------------------------------
    def load_photos(self):
        if "正常" not in self.api_status_label.text():
            QMessageBox.warning(self, "提示", "后端未启动，无法加载照片！")
            return

        try:
            self.statusBar.showMessage("正在加载照片...")
            response = requests.get(f"{self.api_base_url}/photos")
            if response.status_code == 200:
                data = response.json()
                self.photos = data.get('photos', [])
                self.update_photo_list()
                self.photo_count_label.setText(f"照片总数: {len(self.photos)}")
                self.statusBar.showMessage(f"成功加载 {len(self.photos)} 张照片")
            else:
                self.statusBar.showMessage("加载照片失败（API响应错误）")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"加载照片时出错: {str(e)}")
            self.statusBar.showMessage("加载照片时出错")

    def update_photo_list(self):
        self.photo_list.clear()
        for photo in self.photos:
            item_text = f"{photo['title']} ({photo['date_taken'][:10]})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, photo['id'])

            try:
                if photo.get('thumbnail'):
                    thumb_response = requests.get(f"{self.api_base_url}/uploads/thumbnails/{photo['thumbnail']}")
                    if thumb_response.status_code == 200:
                        img_data = thumb_response.content
                        pixmap = QPixmap()
                        pixmap.loadFromData(img_data)
                        scaled_pixmap = pixmap.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                        item.setIcon(QIcon(scaled_pixmap))
            except Exception:
                pass

            self.photo_list.addItem(item)

    def filter_photos(self):
        search_text = self.search_input.text().lower()
        selected_category = self.category_filter.currentText()
        selected_year = self.year_filter.currentText()

        for i in range(self.photo_list.count()):
            item = self.photo_list.item(i)
            photo_id = item.data(Qt.UserRole)
            photo = next((p for p in self.photos if p['id'] == photo_id), None)

            if photo:
                matches_search = (search_text in photo['title'].lower() or 
                                 (photo.get('description') and search_text in photo['description'].lower()))
                matches_category = (selected_category == "全部" or 
                                   self.get_category_display_name(photo['category']) == selected_category)
                photo_year = photo['date_taken'][:4]
                matches_year = (selected_year == "全部" or photo_year == selected_year)

                item.setHidden(not (matches_search and matches_category and matches_year))

    def get_category_display_name(self, category):
        category_map = {
            'class': '班级活动', 'graduation': '毕业照', 'sports': '运动会',
            'activity': '课外活动', 'campus': '校园风景', 'other': '其他'
        }
        return category_map.get(category, category)

    def get_category_internal_name(self, display_name):
        category_map = {
            '班级活动': 'class', '毕业照': 'graduation', '运动会': 'sports',
            '课外活动': 'activity', '校园风景': 'campus', '其他': 'other'
        }
        return category_map.get(display_name, 'other')

    def show_photo_details(self, current_row):
        if current_row < 0:
            return

        item = self.photo_list.item(current_row)
        photo_id = item.data(Qt.UserRole)
        photo = next((p for p in self.photos if p['id'] == photo_id), None)

        if photo:
            self.current_photo_id = photo_id
            self.title_input.setText(photo['title'])
            self.description_input.setPlainText(photo.get('description', ''))

            photo_date = QDate.fromString(photo['date_taken'][:10], 'yyyy-MM-dd')
            self.date_input.setDate(photo_date)

            category_display = self.get_category_display_name(photo['category'])
            category_index = self.category_input.findText(category_display)
            if category_index >= 0:
                self.category_input.setCurrentIndex(category_index)

            try:
                img_response = requests.get(f"{self.api_base_url}/uploads/{photo['filename']}")
                if img_response.status_code == 200:
                    img_data = img_response.content
                    pixmap = QPixmap()
                    pixmap.loadFromData(img_data)
                    scaled_pixmap = pixmap.scaled(
                        self.photo_preview.width(), self.photo_preview.height(),
                        Qt.KeepAspectRatio, Qt.SmoothTransformation
                    )
                    self.photo_preview.setPixmap(scaled_pixmap)
            except Exception as e:
                self.photo_preview.setText(f"加载图片失败: {str(e)}")

    def save_photo_details(self):
        if not self.current_photo_id:
            QMessageBox.warning(self, "警告", "请先选择一张照片")
            return

        try:
            update_data = {
                'title': self.title_input.text(),
                'description': self.description_input.toPlainText(),
                'date_taken': self.date_input.date().toString('yyyy-MM-dd'),
                'category': self.get_category_internal_name(self.category_input.currentText())
            }

            response = requests.put(
                f"{self.api_base_url}/photos/{self.current_photo_id}",
                json=update_data,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                QMessageBox.information(self, "成功", "照片信息已更新")
                self.load_photos()
            else:
                QMessageBox.warning(self, "错误", "更新照片信息失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"更新照片信息时出错: {str(e)}")

    def upload_photo(self):
        if "正常" not in self.api_status_label.text():
            QMessageBox.warning(self, "提示", "后端未启动，无法上传照片！")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择照片", "", "图片文件 (*.png *.jpg *.jpeg *.gif)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'rb') as f:
                files = {'photo': f}
                data = {
                    'title': os.path.basename(file_path).split('.')[0],
                    'description': '通过Lc照相馆管理系统上传',
                    'date_taken': QDate.currentDate().toString('yyyy-MM-dd'),
                    'category': 'other'
                }

                response = requests.post(f"{self.api_base_url}/photos", files=files, data=data)
                if response.status_code == 201:
                    QMessageBox.information(self, "成功", "照片上传成功")
                    self.load_photos()
                else:
                    QMessageBox.warning(self, "错误", "照片上传失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"上传照片时出错: {str(e)}")

    def delete_photo(self):
        if not self.current_photo_id:
            QMessageBox.warning(self, "警告", "请先选择一张照片")
            return

        reply = QMessageBox.question(
            self, "确认删除", "确定要删除这张照片吗？此操作不可撤销。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.No:
            return

        try:
            response = requests.delete(f"{self.api_base_url}/photos/{self.current_photo_id}")
            if response.status_code == 200:
                QMessageBox.information(self, "成功", "照片已删除")
                self.current_photo_id = None
                self.photo_preview.clear()
                self.photo_preview.setText("选择照片预览")
                self.load_photos()
            else:
                QMessageBox.warning(self, "错误", "删除照片失败")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"删除照片时出错: {str(e)}")

    # ------------------------------
    # 窗口关闭处理
    # ------------------------------
    def closeEvent(self, event: QCloseEvent):
        if self.backend_check_thread and self.backend_check_thread.isRunning():
            self.backend_check_thread.stop()
            self.backend_check_thread.wait()

        if self.backend_process:
            self.backend_process.terminate()
            self.backend_process.wait()
            self.statusBar.showMessage("后端服务已关闭")

        event.accept()

# ------------------------------
# 程序入口
# ------------------------------
def main():
    app = QApplication(sys.argv)
    manager = PhotoManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
