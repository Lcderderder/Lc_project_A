import os
import sys
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTextEdit, QMessageBox, QStatusBar)
from PyQt5.QtCore import Qt, QProcess, QTimer, pyqtSignal, QUrl
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply

class PhotoBackendManager(QMainWindow):
    # 自定义信号
    process_output = pyqtSignal(str)
    health_check_result = pyqtSignal(dict)
    
    def __init__(self):
        super().__init__()
        self.is_app_running = False
        self.is_scanning = False
        self.app_process = None
        self.user_requested_close = False
        self.last_health_status = None  # 保存最后一次健康状态
        self.consecutive_failures = 0   # 连续失败次数
        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_health_response)
        
        self.initUI()
        self.centerWindow()
        
        # 连接信号
        self.process_output.connect(self.append_log)
        self.health_check_result.connect(self.update_health_status)
    
    def initUI(self):
        self.setWindowTitle("Lc照相馆 - 后端管理")
        self.setGeometry(100, 100, 1200, 800)
        
        # 设置图标
        icon_path = 'camera_icon.png'
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(QIcon.fromTheme("system-run"))

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # 状态显示区
        status_group = QWidget()
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(10)

        self.backend_status_label = QLabel("后端状态：未启动")
        self.backend_status_label.setFont(QFont("微软雅黑", 14, QFont.Bold))
        self.backend_status_label.setAlignment(Qt.AlignCenter)
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        status_layout.addWidget(self.backend_status_label)

        self.scan_status_label = QLabel("扫描状态：未开始")
        self.scan_status_label.setFont(QFont("微软雅黑", 12))
        self.scan_status_label.setAlignment(Qt.AlignCenter)
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        status_layout.addWidget(self.scan_status_label)

        self.db_status_label = QLabel("数据库状态：未就绪")
        self.db_status_label.setFont(QFont("微软雅黑", 12))
        self.db_status_label.setAlignment(Qt.AlignCenter)
        self.db_status_label.setStyleSheet("color: #ffc107;")
        status_layout.addWidget(self.db_status_label)

        main_layout.addWidget(status_group)

        # 核心按钮
        self.toggle_app_btn = QPushButton("启动 app.py 后端")
        self.toggle_app_btn.setFont(QFont("微软雅黑", 12))
        self.toggle_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.toggle_app_btn.clicked.connect(self.toggleApp)
        main_layout.addWidget(self.toggle_app_btn)

        # 日志显示区域
        log_label = QLabel("系统日志：")
        log_label.setFont(QFont("微软雅黑", 10, QFont.Bold))
        main_layout.addWidget(log_label)

        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        self.log_display.setMinimumHeight(250)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 10pt;
                padding: 5px;
            }
        """)
        main_layout.addWidget(self.log_display)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 - 点击启动后端服务")
        
        # 健康检查定时器
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self.check_health_async)
        self.health_timer.setInterval(3000)  # 3秒检查一次，减少频率
    
    def centerWindow(self):
        """将窗口居中显示在屏幕上"""
        frameGeometry = self.frameGeometry()
        centerPoint = QApplication.desktop().availableGeometry().center()
        frameGeometry.moveCenter(centerPoint)
        self.move(frameGeometry.topLeft())
    
    def toggleApp(self):
        if not self.is_app_running:
            self.startApp()
        else:
            self.stopApp()
    
    def startApp(self):
        try:
            # 清理端口
            self.append_log("INFO 正在清理端口...")
            self.cleanup_port(5000)
            
            self.append_log("INFO 正在启动后端服务...")
            
            # 重置健康状态
            self.last_health_status = None
            self.consecutive_failures = 0
            
            # 使用QProcess启动后端
            self.app_process = QProcess()
            self.app_process.setProcessChannelMode(QProcess.MergedChannels)
            
            # 连接信号
            self.app_process.readyReadStandardOutput.connect(self.handle_process_output)
            self.app_process.finished.connect(self.handle_process_finished)
            self.app_process.errorOccurred.connect(self.handle_process_error)
            
            # 启动进程
            self.app_process.start(sys.executable, ["app.py"])
            
            # 等待进程启动
            if not self.app_process.waitForStarted(5000):  # 5秒超时
                raise Exception("进程启动超时")
                
            self.is_app_running = True
            
            # 更新UI
            self.toggle_app_btn.setText("关闭 app.py 后端")
            self.toggle_app_btn.setStyleSheet("""
                QPushButton {
                    background-color: #dc3545;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 12px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #bb2d3b;
                }
            """)
            self.backend_status_label.setText("后端状态：启动中...")
            self.backend_status_label.setStyleSheet("color: #ffc107;")
            self.status_bar.showMessage("后端启动中...")
            
            # 延迟启动健康检查，给后端一些启动时间
            QTimer.singleShot(5000, self.start_health_check)

        except Exception as e:
            self.append_log(f"ERROR 启动失败: {str(e)}")
            self.resetUIAfterFailure()
    
    def start_health_check(self):
        """启动健康检查"""
        if self.is_app_running:
            self.health_timer.start()
            self.append_log("INFO 开始健康检查...")
    
    def stopApp(self):
        if not self.is_app_running or not self.app_process:
            return

        self.append_log("INFO 正在关闭后端服务...")
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("关闭中...")
        
        # 停止健康检查
        self.health_timer.stop()
        
        # 重置健康状态
        self.last_health_status = None
        self.consecutive_failures = 0
        
        # 异步终止进程
        QTimer.singleShot(0, self.terminate_process_async)
    
    def terminate_process_async(self):
        """异步终止进程"""
        try:
            if self.app_process and self.app_process.state() == QProcess.Running:
                # 先尝试正常终止
                self.app_process.terminate()
                
                # 设置超时，如果2秒内没结束就强制杀死
                QTimer.singleShot(2000, self.kill_process_if_needed)
            else:
                self.on_termination_complete()
                
        except Exception as e:
            self.append_log(f"ERROR 终止进程时出错: {str(e)}")
            self.on_termination_complete()
    
    def kill_process_if_needed(self):
        """如果需要，强制杀死进程"""
        try:
            if self.app_process and self.app_process.state() == QProcess.Running:
                self.append_log("WARN 进程未响应，强制终止...")
                self.app_process.kill()
                # 不等待，直接完成终止
                
            self.on_termination_complete()
            
        except Exception as e:
            self.append_log(f"ERROR 强制终止失败: {str(e)}")
            self.on_termination_complete()
    
    def on_termination_complete(self):
        """进程终止完成"""
        self.is_app_running = False
        
        # 清理端口
        QTimer.singleShot(0, lambda: self.cleanup_port(5000))
        
        # 更新UI
        self.toggle_app_btn.setDisabled(False)
        self.toggle_app_btn.setText("启动 app.py 后端")
        self.toggle_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #218838;
            }
        """)
        
        self.backend_status_label.setText("后端状态：未启动")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.scan_status_label.setText("扫描状态：未开始")
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        self.db_status_label.setText("数据库状态：未就绪")
        self.db_status_label.setStyleSheet("color: #ffc107;")
        
        self.status_bar.showMessage("后端已关闭")
        self.append_log("INFO 后端服务已关闭")
        
        # 清理进程对象
        if self.app_process:
            self.app_process.deleteLater()
            self.app_process = None
        
        # 如果用户请求关闭窗口，现在可以关闭了
        if self.user_requested_close:
            self.user_requested_close = False
            QTimer.singleShot(0, self.close)
    
    def handle_process_output(self):
        """处理进程输出"""
        if self.app_process:
            data = self.app_process.readAllStandardOutput().data()
            try:
                text = data.decode('utf-8').strip()
            except UnicodeDecodeError:
                try:
                    text = data.decode('gbk', errors='replace').strip()
                except:
                    text = f"[无法解码的日志: {data.hex()}]"
            
            if text:
                self.process_output.emit(text)
    
    def handle_process_finished(self, exit_code, exit_status):
        """进程结束回调"""
        if exit_code == 0:
            self.append_log("INFO 进程正常退出")
        else:
            self.append_log(f"WARN 进程异常退出，代码: {exit_code}")
        
        if self.is_app_running:
            self.on_termination_complete()
    
    def handle_process_error(self, error):
        """进程错误回调"""
        error_msg = {
            QProcess.FailedToStart: "进程启动失败",
            QProcess.Crashed: "进程崩溃",
            QProcess.Timedout: "进程超时",
            QProcess.WriteError: "写入错误",
            QProcess.ReadError: "读取错误",
            QProcess.UnknownError: "未知错误"
        }.get(error, "未知错误")
        
        self.append_log(f"ERROR 进程错误: {error_msg}")
    
    def check_health_async(self):
        """异步健康检查"""
        if not self.is_app_running:
            return
            
        try:
            url = QUrl("http://localhost:5000/api/health")
            request = QNetworkRequest(url)
            request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
            request.setHeader(QNetworkRequest.UserAgentHeader, "PhotoManager/1.0")
            request.setAttribute(QNetworkRequest.HttpPipeliningAllowedAttribute, True)
            
            # 设置较短的超时时间
            self.network_manager.get(request)
            
        except Exception as e:
            # 网络请求失败，使用最后一次有效状态
            if self.last_health_status:
                self.health_check_result.emit(self.last_health_status)
            else:
                self.health_check_result.emit({
                    'status': 'unhealthy',
                    'scan_finished': True,
                    'db_ready': False,
                    'message': '健康检查初始化失败'
                })
    
    def handle_health_response(self, reply):
        """处理健康检查响应"""
        try:
            if reply.error() == QNetworkReply.NoError:
                data = reply.readAll().data()
                try:
                    import json
                    health_data = json.loads(data.decode('utf-8'))
                    # 保存最后一次成功的健康状态
                    self.last_health_status = health_data
                    self.consecutive_failures = 0
                    self.health_check_result.emit(health_data)
                except Exception as e:
                    # JSON解析失败，使用最后一次有效状态
                    if self.last_health_status:
                        self.health_check_result.emit(self.last_health_status)
                    else:
                        self.health_check_result.emit({
                            'status': 'unhealthy',
                            'scan_finished': True,
                            'db_ready': False,
                            'message': '解析健康响应失败'
                        })
            else:
                # 网络错误，增加失败计数
                self.consecutive_failures += 1
                
                # 如果连续失败次数较少，使用最后一次有效状态
                if self.last_health_status and self.consecutive_failures <= 3:
                    self.health_check_result.emit(self.last_health_status)
                else:
                    self.health_check_result.emit({
                        'status': 'unhealthy',
                        'scan_finished': True,
                        'db_ready': False,
                        'message': f'网络错误: {reply.errorString()}'
                    })
        finally:
            reply.deleteLater()
    
    def update_health_status(self, health_data):
        """更新健康状态 - 添加状态稳定性逻辑"""
        # 只有在状态确实发生变化时才更新UI
        current_db_ready = health_data.get("db_ready", False)
        current_scan_finished = health_data.get("scan_finished", True)
        
        # 更新后端状态
        if self.is_app_running:
            self.backend_status_label.setText("后端状态：运行中")
            self.backend_status_label.setStyleSheet("color: #28a745;")
        else:
            self.backend_status_label.setText("后端状态：未启动")
            self.backend_status_label.setStyleSheet("color: #dc3545;")

        # 更新扫描状态（只在确实变化时更新）
        self.is_scanning = not current_scan_finished
        if self.is_app_running:
            if self.is_scanning:
                new_scan_text = "扫描状态：自动执行中..."
                new_scan_style = "color: #ffc107;"
            else:
                new_scan_text = "扫描状态：已完成"
                new_scan_style = "color: #28a745;"
            
            # 只在文本确实变化时更新，避免闪烁
            if self.scan_status_label.text() != new_scan_text:
                self.scan_status_label.setText(new_scan_text)
                self.scan_status_label.setStyleSheet(new_scan_style)

        # 更新数据库状态（只在确实变化时更新）
        if current_db_ready:
            message = health_data.get("message", "")
            if "共" in message and "张照片" in message:
                try:
                    photo_count = message.split("共")[1].split("张照片")[0]
                    new_db_text = f"数据库状态：已就绪（共{photo_count}张照片）"
                except:
                    new_db_text = "数据库状态：已就绪"
            else:
                new_db_text = "数据库状态：已就绪"
            new_db_style = "color: #28a745;"
        else:
            new_db_text = "数据库状态：未就绪"
            new_db_style = "color: #ffc107;"
        
        # 只在文本确实变化时更新，避免闪烁
        if self.db_status_label.text() != new_db_text:
            self.db_status_label.setText(new_db_text)
            self.db_status_label.setStyleSheet(new_db_style)

        # 更新状态栏（总是更新）
        self.status_bar.showMessage(f"系统状态：{health_data.get('message', '未知状态')}")
    
    def cleanup_port(self, port):
        """清理端口占用 - 异步执行"""
        try:
            if os.name == 'nt':  # Windows
                import subprocess
                # 使用start命令异步执行清理
                subprocess.Popen(f'netstat -ano | findstr :{port} | findstr LISTENING && taskkill /F /PID %i', 
                               shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:  # Unix/Linux/Mac
                import subprocess
                # 使用nohup异步执行清理
                subprocess.Popen(f'lsof -ti:{port} | xargs kill -9', 
                               shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass  # 忽略清理端口的错误
    
    def append_log(self, log_text):
        timestamp = time.strftime("%H:%M:%S")
        formatted_log = f"[{timestamp}] {log_text}"
        self.log_display.append(formatted_log)
        # 自动滚动到底部
        cursor = self.log_display.textCursor()
        cursor.movePosition(cursor.End)
        self.log_display.setTextCursor(cursor)
    
    def resetUIAfterFailure(self):
        self.toggle_app_btn.setDisabled(False)
        self.toggle_app_btn.setText("启动 app.py 后端")
        self.backend_status_label.setText("后端状态：启动失败")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.status_bar.showMessage("启动失败，请检查日志")
    
    def closeEvent(self, event):
        # 如果后端正在运行，先停止后端，然后延迟关闭
        if self.is_app_running:
            self.user_requested_close = True
            self.stopApp()
            event.ignore()  # 忽略关闭事件，等待后端停止完成
            return
        
        # 停止健康检查定时器
        self.health_timer.stop()
        
        event.accept()

def main():
    app = QApplication(sys.argv)
    manager = PhotoBackendManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
