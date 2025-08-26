import os
import sys
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QLabel, QPushButton, QTextEdit, QStatusBar)
from PyQt5.QtCore import Qt, QProcess, QTimer, pyqtSignal, QUrl
from PyQt5.QtGui import QFont, QIcon, QPalette, QColor
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
import subprocess

class PhotoBackendManager(QMainWindow):
    # 自定义信号
    process_output = pyqtSignal(str)
    health_check_result = pyqtSignal(dict)
    health_status_changed = pyqtSignal(bool)  # 新增：健康状态变化信号（True=正常，False=故障）
    
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
        self.app_pid = None  # 进程PID
        self.health_was_active = False  # 健康检查状态记录
        self.is_stopping = False  # 标识是否正在执行停止流程
        self.port_cleaned = False  # 端口清理标记
        
        self.initUI()
        self.centerWindow()
        
        # 连接信号
        self.process_output.connect(self.append_log)
        self.health_check_result.connect(self.update_health_status)
        self.health_status_changed.connect(self.update_backend_status_health)  # 连接健康状态信号
    
    def initUI(self):
        """初始化用户界面"""
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

        # 后端状态标签（支持富文本显示）
        self.backend_status_label = QLabel("后端状态：未启动")
        self.backend_status_label.setFont(QFont("微软雅黑", 14, QFont.Bold))
        self.backend_status_label.setAlignment(Qt.AlignCenter)
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.backend_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
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
        self.health_timer.setInterval(3000)  # 3秒检查一次
    
    def centerWindow(self):
        """将窗口居中显示在屏幕上"""
        frameGeometry = self.frameGeometry()
        centerPoint = QApplication.desktop().availableGeometry().center()
        frameGeometry.moveCenter(centerPoint)
        self.move(frameGeometry.topLeft())
    
    def toggleApp(self):
        """切换后端服务状态（启动/停止）"""
        if not self.is_app_running:
            self.startApp()
        else:
            self.stopApp()
    
    def startApp(self):
        """启动后端服务"""
        try:
            # 检测端口占用
            self.append_log("INFO 正在检测端口占用...")
            port = 5000
            pids = []
            
            # 尝试解决端口占用
            try:
                result = subprocess.check_output(
                    f'netstat -ano | findstr :{port} | findstr LISTENING',
                    shell=True,
                    stderr=subprocess.STDOUT,
                    text=True
                )
                for line in result.strip().split('\n'):
                    if line.strip():
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pids.append(parts[-1])
                pids = list(set(pids))
            
            except subprocess.CalledProcessError:
                self.append_log(f"INFO 端口 {port} 未被占用，无需清理")
            except Exception as e:
                raise Exception(f"端口检测失败：{str(e)}")
            
            # 清理端口（仅当被占用时）
            if pids:
                self.append_log(f"INFO 发现端口 {port} 被进程占用（PID：{', '.join(pids)}），尝试清理...")
                failed_pids = []
                
                for pid in pids:
                    try:
                        subprocess.check_output(
                            f'taskkill /F /PID {pid}',
                            shell=True,
                            stderr=subprocess.STDOUT,
                            text=True
                        )
                    except subprocess.CalledProcessError as e:
                        failed_pids.append(f"PID {pid}（错误：{e.output.strip()}）")
                
                if failed_pids:
                    error_msg = (
                        f"ERROR 端口 {port} 清理失败！以下进程未能关闭：{', '.join(failed_pids)}\n"
                        f"请手动清理端口：打开任务管理器 → 详细信息 → 查找对应PID并结束进程"
                    )
                    self.append_log(error_msg)
                    self.resetUIAfterFailure()
                    return  # 终止启动流程
            
                self.append_log(f"INFO 端口 {port} 已成功清理")
                
            self.append_log("INFO 正在启动后端服务...")
            
            # 重置健康状态
            self.last_health_status = None
            self.consecutive_failures = 0
            self.port_cleaned = False
            
            # 使用QProcess启动后端
            self.app_process = QProcess()
            self.app_process.setProcessChannelMode(QProcess.MergedChannels)
            
            # 连接信号
            self.app_process.readyReadStandardOutput.connect(self.handle_process_output)
            self.app_process.finished.connect(self._on_process_finished)
            self.app_process.errorOccurred.connect(self.handle_process_error)
            
            # 启动进程
            self.app_process.start(sys.executable, ["app.py"])
            
            # 等待进程启动（3秒超时）
            if not self.app_process.waitForStarted(3000):
                raise Exception("进程启动超时（可能app.py不存在或依赖缺失）")
                
            self.is_app_running = True
            self.app_pid = self.app_process.pid()  # 保存进程PID
            
            # 显示PID（转换为整数）
            try:
                pid_int = int(self.app_pid)
                self.append_log(f"INFO 后端进程已启动，PID：{pid_int}")
            except:
                self.append_log(f"INFO 后端进程已启动，PID：{self.app_pid}")
            
            # 更新UI - 初始状态为"启动中"，不显示健康状态
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
            
            # 延迟启动健康检查
            QTimer.singleShot(2000, self.start_health_check)

        except Exception as e:
            self.append_log(f"ERROR 启动失败: {str(e)}")
            self.resetUIAfterFailure()
    
    def start_health_check(self):
        """启动健康检查"""
        try:
            if self.is_app_running:
                if self.health_timer.isActive():
                    self.health_timer.stop()
                self.health_timer.start()
                self.append_log("INFO 开始健康检查（每3秒一次）...")
        except Exception as e:
            error_msg = f"ERROR 启动健康检查失败: {str(e)}"
            self.log_display.append(f"[{time.strftime('%H:%M:%S')}] {error_msg}")
            self.status_bar.showMessage("健康检查启动失败")
            # 发送健康状态故障信号
            self.health_status_changed.emit(False)
    
    def stopApp(self):
        """停止后端服务"""
        if not self.is_app_running or not self.app_process:
            self.append_log("WARN 后端未在运行，无需关闭")
            return

        # 标记为正在停止
        self.is_stopping = True
        
        # 保存关闭前的按钮状态
        self.saved_btn = {
            "text": self.toggle_app_btn.text(),
            "style": self.toggle_app_btn.styleSheet()
        }

        # 更新按钮状态
        self.toggle_app_btn.setText("关闭中...")
        self.toggle_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
                font-weight: bold;
            }
        """)
        self.toggle_app_btn.setDisabled(True)
        self.append_log("INFO 正在关闭后端服务...")

        # 停止健康检查
        self.health_was_active = self.health_timer.isActive()
        if self.health_was_active:
            self.health_timer.stop()
            self.append_log("INFO 已暂停健康检查")

        # 尝试正常终止
        self.append_log("INFO 发送终止信号...")
        self.app_process.terminate()

        # 设置超时检测（10秒）
        self.close_timeout_timer = QTimer()
        self.close_timeout_timer.setSingleShot(True)
        self.close_timeout_timer.timeout.connect(self._on_close_timeout)
        self.close_timeout_timer.start(10000)
    
    def _on_close_timeout(self):
        """关闭超时处理 - 强制终止"""
        if self.app_process and self.app_process.state() == QProcess.Running:
            self.append_log("WARN 正常关闭超时（10秒），尝试强制终止...")
            try:
                # Windows强制终止
                if os.name == 'nt' and self.app_pid:
                    pid_int = int(self.app_pid)
                    subprocess.run(
                        f'taskkill /F /PID {pid_int}',
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True
                    )
                    self.append_log(f"INFO 已执行 taskkill /F /PID {pid_int}")
                
                # 跨平台保底方案
                self.app_process.kill()
                self.append_log("INFO 已发送强制终止信号（kill）")
                
                # 检查终止结果
                QTimer.singleShot(1000, self._check_process_killed)
            except Exception as e:
                self.append_log(f"ERROR 强制终止失败: {str(e)}")
                self._restore_stop_failure_ui()
        else:
            self.append_log("INFO 进程已终止，无需超时处理")
            self._on_process_finished(0, 0)
    
    def _check_process_killed(self):
        """检查进程是否已终止"""
        if self.app_process and self.app_process.state() == QProcess.Running:
            self.append_log("ERROR 强制终止仍失败！进程可能残留（需手动结束）")
            self._restore_stop_failure_ui()
        else:
            self.append_log("INFO 进程已成功终止")
            self._on_process_finished(0, 0)
    
    def _restore_stop_failure_ui(self):
        """终止失败时恢复UI状态"""
        self.is_stopping = False
        self.toggle_app_btn.setText(self.saved_btn["text"])
        self.toggle_app_btn.setStyleSheet(self.saved_btn["style"])
        self.toggle_app_btn.setDisabled(False)
        self.status_bar.showMessage("关闭失败，后端可能仍在运行")
        if self.health_was_active:
            self.health_timer.start()
    
    def _on_process_finished(self, exit_code, exit_status):
        """进程结束处理"""
        # 防止重复处理
        if self.port_cleaned:
            self.port_cleaned = False
            return
            
        # 停止超时检测
        if hasattr(self, 'close_timeout_timer') and self.close_timeout_timer.isActive():
            self.close_timeout_timer.stop()
        
        # 重置停止状态标识
        self.is_stopping = False
        
        # 记录退出状态
        if exit_code == 0:
            self.append_log("INFO 进程正常退出（exit code: 0）")
        else:
            if exit_status == QProcess.CrashExit:
                self.append_log(f"INFO 进程已被强制终止（exit code: {exit_code}）")
            else:
                self.append_log(f"WARN 进程异常退出（exit code: {exit_code}，status: {exit_status}）")
        
        # 更新状态
        self.is_app_running = False
        if self.app_process:
            self.app_process.deleteLater()
            self.app_process = None
        
        # 清理端口（仅一次）
        self.port_cleaned = True
        self.cleanup_port(5000)
        
        # 更新UI
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
        self.toggle_app_btn.setDisabled(False)
        self.backend_status_label.setText("后端状态：未启动")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.scan_status_label.setText("扫描状态：未开始")
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        self.db_status_label.setText("数据库状态：未就绪")
        self.db_status_label.setStyleSheet("color: #ffc107;")
        self.status_bar.showMessage("后端已关闭")
        
        # 处理用户关闭请求
        if self.user_requested_close:
            self.user_requested_close = False
            QTimer.singleShot(0, self.close)
    
    def handle_process_output(self):
        """处理进程输出（过滤健康检查的HTTP日志）"""
        if self.app_process:
            data = self.app_process.readAllStandardOutput().data()
            try:
                text = data.decode('utf-8').strip()
            except UnicodeDecodeError:
                try:
                    text = data.decode('gbk', errors='replace').strip()
                except:
                    text = f"[无法解码的日志: {data.hex()[:32]}...]"
            
            # 过滤掉健康检查的HTTP请求日志
            if text and "/api/health HTTP/1.1" not in text:
                self.process_output.emit(text)
    
    def handle_process_error(self, error):
        """处理进程错误"""
        # 正在停止过程中产生的错误均为预期行为
        if self.is_stopping:
            self.append_log("INFO 进程终止过程中产生预期错误（强制终止导致）")
            return
            
        # 真正的意外错误
        error_map = {
            QProcess.FailedToStart: "进程启动失败（可能app.py缺失或Python环境错误）",
            QProcess.Crashed: "进程意外崩溃（非强制终止，需检查后端代码）",
            QProcess.Timedout: "进程操作超时",
            QProcess.WriteError: "向进程写入数据失败",
            QProcess.ReadError: "从进程读取日志失败",
            QProcess.UnknownError: "未知进程错误"
        }
        error_msg = error_map.get(error, "未知错误")
        self.append_log(f"ERROR 进程错误: {error_msg}")
        
        # 发送健康状态故障信号
        if self.is_app_running:
            self.health_status_changed.emit(False)
            self.resetUIAfterFailure()
    
    def check_health_async(self):
        """异步健康检查"""
        if not self.is_app_running:
            return
            
        try:
            url = QUrl("http://localhost:5000/api/health")
            request = QNetworkRequest(url)
            request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
            request.setHeader(QNetworkRequest.UserAgentHeader, "PhotoManager/1.0")
            request.setTransferTimeout(5000)  # 5秒超时
            self.network_manager.get(request)
            
        except Exception as e:
            self.append_log(f"ERROR 健康检查请求失败: {str(e)}")
            # 发送健康状态故障信号
            self.health_status_changed.emit(False)
    
    def handle_health_response(self, reply):
        """处理健康检查响应"""
        try:
            if reply.error() == QNetworkReply.NoError:
                data = reply.readAll().data()
                try:
                    import json
                    health_data = json.loads(data.decode('utf-8'))
                    self.last_health_status = health_data
                    self.consecutive_failures = 0
                    self.health_check_result.emit(health_data)
                    # 发送健康状态正常信号
                    self.health_status_changed.emit(True)
                except json.JSONDecodeError:
                    self.append_log("WARN 健康检查响应不是合法JSON格式")
                    # 发送健康状态故障信号
                    self.health_status_changed.emit(False)
                except Exception as e:
                    self.append_log(f"WARN 解析健康响应出错: {str(e)}")
                    # 发送健康状态故障信号
                    self.health_status_changed.emit(False)
            else:
                # 网络错误处理
                self.consecutive_failures += 1
                error_msg = f'网络错误: {reply.errorString()}'
                self.append_log(f"WARN 健康检查失败: {error_msg}")
                # 连续失败3次以上才标记为故障
                if self.consecutive_failures > 3:
                    self.health_status_changed.emit(False)
                elif self.last_health_status:
                    self.health_check_result.emit(self.last_health_status)
        finally:
            reply.deleteLater()
    
    def update_health_status(self, health_data):
        """更新健康状态UI"""
        if not self.is_app_running:
            return

        current_db_ready = health_data.get("db_ready", False)
        current_scan_finished = health_data.get("scan_finished", True)
        current_message = health_data.get("message", "未知状态")

        # 更新扫描状态
        new_scan_text = "扫描状态：自动执行中..." if not current_scan_finished else "扫描状态：已完成"
        new_scan_style = "color: #ffc107;" if not current_scan_finished else "color: #28a745;"
        if self.scan_status_label.text() != new_scan_text:
            self.scan_status_label.setText(new_scan_text)
            self.scan_status_label.setStyleSheet(new_scan_style)

        # 更新数据库状态
        if current_db_ready:
            if "共" in current_message and "张照片" in current_message:
                try:
                    photo_count = current_message.split("共")[1].split("张照片")[0].strip()
                    new_db_text = f"数据库状态：已就绪（共{photo_count}张照片）"
                except:
                    new_db_text = "数据库状态：已就绪"
            else:
                new_db_text = "数据库状态：已就绪"
            new_db_style = "color: #28a745;"
        else:
            new_db_text = "数据库状态：未就绪"
            new_db_style = "color: #ffc107;"
        if self.db_status_label.text() != new_db_text:
            self.db_status_label.setText(new_db_text)
            self.db_status_label.setStyleSheet(new_db_style)

        # 更新状态栏
        self.status_bar.showMessage(f"系统状态：{current_message}")
    
    def update_backend_status_health(self, is_healthy):
        """更新后端状态中的健康检查信息"""
        if not self.is_app_running:
            return
            
        # 基础文本：后端状态：运行中
        base_text = '<span style="color: #28a745;">后端状态：运行中</span>'
        
        if is_healthy:
            # 健康状态：绿色的"实时检测进行中"
            self.backend_status_label.setText(
                f'{base_text} <span style="color: #28a745;">(实时检测进行中)</span>'
            )
        else:
            # 故障状态：红色的"实时监测故障"
            self.backend_status_label.setText(
                f'{base_text} <span style="color: #dc3545;">(实时监测故障)</span>'
            )
        
        # 确保标签支持富文本
        self.backend_status_label.setTextFormat(Qt.RichText)
    
    def cleanup_port(self, port):
        """清理端口占用"""
        try:
            if os.name == 'nt':
                subprocess.Popen(
                    f'start /min cmd /c "netstat -ano | findstr :{port} | findstr LISTENING && taskkill /F /PID %i"',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                self.append_log(f"INFO 已触发端口 {port} 清理（异步执行）")
        except Exception as e:
            self.append_log(f"WARN 清理端口 {port} 时出错: {str(e)}")
    
    def append_log(self, log_text):
        """添加日志"""
        timestamp = time.strftime("%H:%M:%S")
        formatted_log = f"[{timestamp}] {log_text}"
        self.log_display.append(formatted_log)
        # 自动滚动到底部
        cursor = self.log_display.textCursor()
        cursor.movePosition(cursor.End)
        self.log_display.setTextCursor(cursor)
    
    def resetUIAfterFailure(self):
        """启动失败时重置UI"""
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
        self.backend_status_label.setText("后端状态：启动失败")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.status_bar.showMessage("启动失败，请检查日志")
    
    def closeEvent(self, event):
        """窗口关闭事件"""
        if self.is_app_running:
            self.user_requested_close = True
            self.stopApp()
            event.ignore()
            self.append_log("INFO 等待后端停止后关闭窗口...")
            return
        
        if self.health_timer.isActive():
            self.health_timer.stop()
        
        event.accept()

def main():
    """程序入口"""
    app = QApplication(sys.argv)
    manager = PhotoBackendManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
