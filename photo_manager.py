import os
import sys
import time
import signal
import subprocess
import psutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTextEdit, QMessageBox, QStatusBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

# 检查psutil是否可用
PSUTIL_WORKING = False
try:
    import psutil
    PSUTIL_WORKING = True
except ImportError:
    pass

class TerminationThread(QThread):
    """后台线程处理进程终止"""
    termination_finished = pyqtSignal(bool, str)

    def __init__(self, app_process, app_pid, parent=None):
        super().__init__(parent)
        self.app_process = app_process
        self.app_pid = app_pid
        self.running = True

    def run(self):
        process_terminated = False
        message = ""
        port_cleaned = False
        
        # 第一步：尝试优雅关闭
        if self.app_process and self.running:
            try:
                if os.name == 'nt':
                    self.app_process.terminate()
                else:
                    os.kill(self.app_pid, signal.SIGTERM)
                
                # 等待进程结束
                try:
                    self.app_process.wait(timeout=3)
                    process_terminated = True
                    message = "进程已正常关闭"
                except (subprocess.TimeoutExpired, TimeoutError):
                    if not self.running:
                        return
                    # 强制关闭
                    try:
                        if os.name == 'nt':
                            self.app_process.kill()
                        else:
                            os.kill(self.app_pid, signal.SIGKILL)
                        self.app_process.wait(timeout=2)
                        process_terminated = True
                        message = "进程已强制关闭"
                    except Exception as e:
                        message = f"强制关闭失败: {str(e)}"
            except Exception as e:
                message = f"关闭进程失败: {str(e)}"
        
        # 第二步：psutil清理
        if not process_terminated and PSUTIL_WORKING and self.running:
            try:
                port_cleaned = self.cleanup_port(5000)
                
                if self.app_pid:
                    try:
                        process = psutil.Process(self.app_pid)
                        process.terminate()
                        process.wait(timeout=2)
                        process_terminated = True
                        message = "使用psutil关闭进程成功"
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        process_terminated = True
                        message = "进程已不存在"
                    except Exception as e:
                        if not self.running:
                            return
                        try:
                            process = psutil.Process(self.app_pid)
                            process.kill()
                            process.wait(timeout=2)
                            process_terminated = True
                            message = "进程已强制杀死"
                        except Exception as e:
                            message = f"psutil杀死进程失败: {str(e)}"
                
                if port_cleaned:
                    message += "，端口已清理"
            except Exception as e:
                message = f"psutil操作出错: {str(e)}"
        
        # 第三步：系统命令清理
        if not process_terminated and self.running:
            port_cleaned = self.cleanup_port_system(5000)
            if port_cleaned:
                process_terminated = True
                message = "使用系统命令清理端口成功"
        
        self.termination_finished.emit(process_terminated, message)

    def cleanup_port(self, port):
        cleaned = False
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    try:
                        process = psutil.Process(conn.pid)
                        process.terminate()
                        process.wait(timeout=1)
                        cleaned = True
                    except Exception:
                        continue
        except Exception:
            pass
        return cleaned

    def cleanup_port_system(self, port):
        cleaned = False
        try:
            if os.name == 'nt':
                result = subprocess.run(
                    ['netstat', '-ano', '|', 'findstr', f':{port}'],
                    capture_output=True, text=True, shell=True, timeout=5
                )
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if f':{port}' in line and 'LISTENING' in line:
                            parts = line.split()
                            if len(parts) >= 5:
                                pid = parts[-1]
                                subprocess.run(
                                    ['taskkill', '/F', '/PID', pid],
                                    capture_output=True, timeout=3
                                )
                                cleaned = True
            else:
                result = subprocess.run(
                    ['lsof', '-ti', f':{port}'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        if pid and pid.isdigit():
                            subprocess.run(
                                ['kill', '-9', pid],
                                capture_output=True, timeout=3
                            )
                            cleaned = True
        except Exception:
            pass
        return cleaned

    def stop(self):
        self.running = False
        self.wait()

class LogThread(QThread):
    """日志输出线程"""
    log_received = pyqtSignal(str)

    def __init__(self, process, parent=None):
        super().__init__(parent)
        self.process = process
        self.running = True

    def run(self):
        while self.running and self.process.poll() is None:
            # 读取原始字节流，处理编码问题
            line_bytes = self.process.stdout.readline()
            if line_bytes:
                try:
                    # 尝试用UTF-8解码
                    line = line_bytes.decode('utf-8').strip()
                except UnicodeDecodeError:
                    # 解码失败时用GBK尝试，仍失败则忽略错误字符
                    try:
                        line = line_bytes.decode('gbk', errors='replace').strip()
                    except:
                        line = f"[无法解码的日志: {line_bytes.hex()}]"
                self.log_received.emit(line)
            else:
                time.sleep(0.1)

    def stop(self):
        self.running = False
        self.wait()

class HealthCheckThread(QThread):
    """健康检查线程"""
    health_updated = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = True

    def run(self):
        import requests
        while self.running:
            try:
                response = requests.get("http://localhost:5000/api/health", timeout=2)
                if response.status_code == 200:
                    self.health_updated.emit(response.json())
            except Exception:
                self.health_updated.emit({
                    'status': 'unhealthy',
                    'scan_finished': True,
                    'db_ready': False,
                    'message': '无法连接后端'
                })
            time.sleep(2)  # 每2秒检查一次

    def stop(self):
        self.running = False
        self.wait()

class PhotoBackendManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.is_app_running = False
        self.is_scanning = False
        self.app_process = None
        self.app_pid = None
        self.log_thread = None
        self.health_thread = None
        self.termination_thread = None
        self.initUI()
        # 窗口居中显示
        self.centerWindow()

    def initUI(self):
        self.setWindowTitle("Lc照相馆 - 后端管理")
        self.setGeometry(100, 100, 800, 600)  # 初始位置(100,100)，大小800x600
        
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

    def centerWindow(self):
        """将窗口居中显示在屏幕上"""
        # 获取窗口大小
        frameGeometry = self.frameGeometry()
        # 获取屏幕中心点
        centerPoint = QApplication.desktop().availableGeometry().center()
        # 将窗口中心与屏幕中心对齐
        frameGeometry.moveCenter(centerPoint)
        # 移动窗口到计算出的位置
        self.move(frameGeometry.topLeft())

    def toggleApp(self):
        if not self.is_app_running:
            self.startApp()
        else:
            self.stopApp()

    def startApp(self):
        try:
            # 清理端口
            self.append_log("INFO 正在检查并清理端口...")
            temp_terminator = TerminationThread(None, None)
            port_cleaned = temp_terminator.cleanup_port_system(5000)
            if port_cleaned:
                self.append_log("INFO 端口5000已清理")
            else:
                self.append_log("INFO 端口5000未被占用或清理失败")
            
            self.append_log("INFO 正在启动后端服务...")
            
            # 启动后端进程
            self.app_process = subprocess.Popen(
                [sys.executable, "app.py"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=False,  # 以字节流方式读取，后续手动解码
                bufsize=1
            )
            self.app_pid = self.app_process.pid
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
            self.status_bar.showMessage(f"后端已启动，PID: {self.app_pid}")

            # 启动日志线程
            self.log_thread = LogThread(self.app_process)
            self.log_thread.log_received.connect(self.append_log)
            self.log_thread.start()

            # 启动健康检查线程
            self.health_thread = HealthCheckThread()
            self.health_thread.health_updated.connect(self.updateHealthStatus)
            self.health_thread.start()

        except Exception as e:
            self.append_log(f"ERROR 启动失败: {str(e)}")
            self.resetUIAfterFailure()

    def stopApp(self):
        if not self.is_app_running:
            return

        self.append_log("INFO 正在关闭后端服务...")
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("关闭中...")

        # 停止健康检查和日志线程
        if self.health_thread:
            self.health_thread.stop()
            self.health_thread = None
        if self.log_thread:
            self.log_thread.stop()
            self.log_thread = None

        # 启动终止线程
        self.termination_thread = TerminationThread(self.app_process, self.app_pid)
        self.termination_thread.termination_finished.connect(self.onTerminationFinished)
        self.termination_thread.start()

    def onTerminationFinished(self, process_terminated, message):
        self.append_log(f"INFO {message}")

        # 重置状态
        self.is_app_running = False
        self.is_scanning = False
        self.app_process = None
        self.app_pid = None
        self.termination_thread = None

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
        
        if process_terminated:
            self.status_bar.showMessage("后端已成功关闭")
            self.append_log("INFO 后端服务已完全关闭")
        else:
            self.status_bar.showMessage("关闭后端时遇到问题")
            self.append_log("WARN 关闭后端时可能遇到问题")

    def updateHealthStatus(self, health_data):
        if self.is_app_running:
            self.backend_status_label.setText("后端状态：运行中")
            self.backend_status_label.setStyleSheet("color: #28a745;")
        else:
            self.backend_status_label.setText("后端状态：未启动")
            self.backend_status_label.setStyleSheet("color: #dc3545;")

        # 同步扫描状态
        self.is_scanning = not health_data.get("scan_finished", True)
        if self.is_app_running:
            if self.is_scanning:
                self.toggle_app_btn.setText("关闭 app.py 后端（扫描中）")
                self.scan_status_label.setText("扫描状态：自动执行中...")
                self.scan_status_label.setStyleSheet("color: #ffc107;")
            else:
                self.toggle_app_btn.setText("关闭 app.py 后端")
                self.scan_status_label.setText("扫描状态：已完成")
                self.scan_status_label.setStyleSheet("color: #28a745;")
                self.append_log("INFO 扫描已完成")
        else:
            self.toggle_app_btn.setText("启动 app.py 后端")

        # 同步数据库状态
        if health_data.get("db_ready", False):
            message = health_data.get("message", "")
            if "共" in message and "张照片" in message:
                try:
                    photo_count = message.split("共")[1].split("张照片")[0]
                    self.db_status_label.setText(f"数据库状态：已就绪（共{photo_count}张照片）")
                except:
                    self.db_status_label.setText("数据库状态：已就绪")
            else:
                self.db_status_label.setText("数据库状态：已就绪")
            self.db_status_label.setStyleSheet("color: #28a745;")
        else:
            self.db_status_label.setText("数据库状态：未就绪")
            self.db_status_label.setStyleSheet("color: #ffc107;")

        # 同步状态栏
        self.status_bar.showMessage(f"系统状态：{health_data.get('message', '未知状态')}")

    def resetUIAfterFailure(self):
        self.toggle_app_btn.setDisabled(False)
        self.toggle_app_btn.setText("启动 app.py 后端")
        self.backend_status_label.setText("后端状态：启动失败")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.status_bar.showMessage("启动失败，请检查日志")

    def append_log(self, log_text):
        timestamp = time.strftime("%H:%M:%S")
        formatted_log = f"[{timestamp}] {log_text}"
        self.log_display.append(formatted_log)
        # 自动滚动到底部
        cursor = self.log_display.textCursor()
        cursor.movePosition(cursor.End)
        self.log_display.setTextCursor(cursor)

    def closeEvent(self, event):
        if self.is_app_running:
            reply = QMessageBox.question(
                self, '确认关闭',
                '后端服务正在运行，确定要关闭吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.stopApp()
                # 等待进程终止
                for _ in range(10):
                    if not self.is_app_running:
                        break
                    time.sleep(0.5)
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

def main():
    app = QApplication(sys.argv)
    manager = PhotoBackendManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
