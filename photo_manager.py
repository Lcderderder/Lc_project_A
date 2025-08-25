import sys
import os
import subprocess
import time
import requests
import threading
import signal
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QStatusBar, QTextEdit, QHBoxLayout, 
                             QMessageBox)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

# 全局变量，标记psutil状态
HAS_PSUTIL = False
PSUTIL_WORKING = False
psutil_error = ""

try:
    import psutil
    HAS_PSUTIL = True
    try:
        psutil.process_iter()
        PSUTIL_WORKING = True
    except Exception as e:
        PSUTIL_WORKING = False
        psutil_error = str(e)
except ImportError:
    psutil_error = "未安装psutil库"

class APIHealthCheckThread(QThread):
    health_result = pyqtSignal(dict)
    
    def __init__(self, api_url):
        super().__init__()
        self.api_url = api_url
        self.running = True

    def run(self):
        while self.running:
            try:
                res = requests.get(self.api_url, timeout=5)  # 增加超时时间
                if res.status_code == 200:
                    self.health_result.emit(res.json())
                else:
                    self.health_result.emit({
                        "backend_running": False,
                        "db_ready": False,
                        "scan_finished": False,
                        "message": "后端响应异常"
                    })
            except requests.exceptions.ConnectionError:
                self.health_result.emit({
                    "backend_running": False,
                    "db_ready": False,
                    "scan_finished": False,
                    "message": "后端未启动或端口占用"
                })
            except requests.exceptions.Timeout:
                self.health_result.emit({
                    "backend_running": True,  # 后端可能在运行但响应慢
                    "db_ready": False,
                    "scan_finished": False,
                    "message": "后端响应超时，可能正在扫描中"
                })
            except Exception as e:
                self.health_result.emit({
                    "backend_running": False,
                    "db_ready": False,
                    "scan_finished": False,
                    "message": f"检测错误：{str(e)[:15]}"
                })
            time.sleep(3)  # 增加检查间隔

    def stop(self):
        self.running = False
        self.wait()

class LogReaderThread(QThread):
    log_signal = pyqtSignal(str)
    
    def __init__(self, process):
        super().__init__()
        self.process = process
        self.running = True

    def run(self):
        while self.running and self.process.poll() is None:
            try:
                line = self.process.stdout.readline()
                if line:
                    decoded_line = line.strip()
                    if decoded_line:
                        self.log_signal.emit(decoded_line)
            except Exception as e:
                self.log_signal.emit(f"日志读取错误：{str(e)}")
                break
            time.sleep(0.1)

    def stop(self):
        self.running = False
        self.wait()

class ProcessTerminationThread(QThread):
    """重写：异步进程终止线程，解决阻塞问题"""
    termination_finished = pyqtSignal(bool, str)
    
    def __init__(self, app_pid, app_process):
        super().__init__()
        self.app_pid = app_pid
        self.app_process = app_process

    def run(self):
        process_terminated = False
        message = ""
        port_cleaned = False
        
        # 第一步：尝试优雅关闭
        if self.app_process:
            try:
                # 尝试正常终止
                if os.name == 'nt':  # Windows
                    self.app_process.terminate()
                else:  # Unix/Linux
                    os.kill(self.app_pid, signal.SIGTERM)
                
                # 等待进程结束
                try:
                    self.app_process.wait(timeout=3)
                    process_terminated = True
                    message = "进程已正常关闭"
                except (subprocess.TimeoutExpired, TimeoutError):
                    # 正常关闭超时，尝试强制关闭
                    try:
                        if os.name == 'nt':
                            self.app_process.kill()
                        else:
                            os.kill(self.app_pid, signal.SIGKILL)
                        self.app_process.wait(timeout=2)
                        process_terminated = True
                        message = "进程已强制关闭"
                    except:
                        message = "强制关闭失败"
            except Exception as e:
                message = f"关闭进程失败: {str(e)}"
        
        # 第二步：如果进程仍然存在或psutil可用，使用psutil清理
        if not process_terminated and PSUTIL_WORKING:
            try:
                # 清理占用5000端口的进程
                port_cleaned = self.cleanup_port(5000)
                
                # 如果知道PID，尝试终止特定进程
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
                    except Exception:
                        # 如果终止失败，尝试强制杀死
                        try:
                            process = psutil.Process(self.app_pid)
                            process.kill()
                            process.wait(timeout=2)
                            process_terminated = True
                            message = "进程已强制杀死"
                        except:
                            pass
                
                if port_cleaned:
                    message += "，端口已清理"
                    
            except Exception as e:
                message = f"使用psutil关闭时出错: {str(e)}"
        
        # 第三步：如果以上都失败，尝试系统命令清理
        if not process_terminated:
            port_cleaned = self.cleanup_port_system(5000)
            if port_cleaned:
                process_terminated = True
                message = "使用系统命令清理端口成功"
        
        self.termination_finished.emit(process_terminated, message)

    def cleanup_port(self, port):
        """使用psutil清理端口占用"""
        cleaned = False
        try:
            for conn in psutil.net_connections(kind='inet'):
                if conn.laddr.port == port and conn.status == 'LISTEN':
                    try:
                        process = psutil.Process(conn.pid)
                        process.terminate()
                        process.wait(timeout=1)
                        cleaned = True
                    except:
                        try:
                            process = psutil.Process(conn.pid)
                            process.kill()
                            process.wait(timeout=1)
                            cleaned = True
                        except:
                            continue
        except:
            pass
        return cleaned

    def cleanup_port_system(self, port):
        """使用系统命令清理端口占用"""
        cleaned = False
        try:
            if os.name == 'nt':  # Windows
                # 查找占用端口的进程
                result = subprocess.run(
                    ['netstat', '-ano', '|', 'findstr', f':{port}'],
                    capture_output=True, text=True, shell=True
                )
                if result.returncode == 0:
                    lines = result.stdout.split('\n')
                    for line in lines:
                        if f':{port}' in line and 'LISTENING' in line:
                            parts = line.split()
                            pid = parts[-1]
                            # 终止进程
                            subprocess.run(['taskkill', '/F', '/PID', pid], 
                                         capture_output=True)
                            cleaned = True
            else:  # Unix/Linux
                # 查找占用端口的进程
                result = subprocess.run(
                    ['lsof', '-ti', f':{port}'],
                    capture_output=True, text=True
                )
                if result.returncode == 0:
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        if pid:
                            # 终止进程
                            subprocess.run(['kill', '-9', pid], 
                                         capture_output=True)
                            cleaned = True
        except:
            pass
        return cleaned

class PhotoBackendManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_health_url = "http://localhost:5000/api/health"
        self.app_process = None
        self.app_pid = None
        self.is_app_running = False
        self.is_scanning = False
        self.health_thread = None
        self.log_thread = None
        self.termination_thread = None
        self.initUI()
        self.centerWindow()
        self.check_psutil()

    def check_psutil(self):
        if not HAS_PSUTIL:
            self.append_log("WARN 未检测到psutil库，进程管理功能受限")
            self.append_log("INFO 建议安装: pip install psutil")
        elif not PSUTIL_WORKING:
            self.append_log(f"WARN psutil库异常：{psutil_error}")
        else:
            self.append_log("INFO psutil库检测正常")

    def initUI(self):
        self.setWindowTitle("Lc照相馆 - 后端管理")
        self.setGeometry(100, 100, 800, 600)
        
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
        screen_geo = QApplication.primaryScreen().availableGeometry()
        window_geo = self.frameGeometry()
        window_geo.moveCenter(screen_geo.center())
        self.move(window_geo.topLeft())

    def toggleApp(self):
        if not self.is_app_running:
            self.startApp()
        else:
            self.stopApp()

    def startApp(self):
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("启动中...")
        self.backend_status_label.setText("后端状态：启动中...")
        self.backend_status_label.setStyleSheet("color: #ffc107;")
        self.status_bar.showMessage("正在启动后端服务...")
        self.log_display.clear()

        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))
            app_path = os.path.join(project_dir, "app.py")
            
            if not os.path.exists(app_path):
                raise FileNotFoundError(f"未找到 app.py")

            # 检查端口是否被占用
            if self.is_port_in_use(5000):
                self.append_log("WARN 端口5000已被占用，尝试清理...")
                self.cleanup_port(5000)

            # 启动进程
            self.app_process = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
                universal_newlines=True,
                encoding='utf-8',
                errors='replace'
            )

            self.app_pid = self.app_process.pid
            self.append_log(f"INFO 后端进程启动，PID：{self.app_pid}")

            # 启动日志读取线程
            self.log_thread = LogReaderThread(self.app_process)
            self.log_thread.log_signal.connect(self.append_log)
            self.log_thread.start()

            # 等待进程启动
            time.sleep(2)
            if self.app_process.poll() is None:
                self.is_app_running = True
                self.updateUIForRunningState("启动中")
                self.startAPIHealthCheck()
            else:
                output, _ = self.app_process.communicate()
                error_msg = output[:100] + "..." if output else "进程启动失败"
                raise Exception(f"启动失败：{error_msg}")

        except Exception as e:
            error_msg = f"ERROR 启动后端失败：{str(e)}"
            self.append_log(error_msg)
            self.resetUIAfterFailure()
            
            # 清理进程
            if self.app_process:
                try:
                    self.app_process.terminate()
                    self.app_process.wait(timeout=1)
                except:
                    pass
                self.app_process = None
            self.app_pid = None

    def stopApp(self):
        """关闭后端应用 - 重写版本"""
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("关闭中...")
        self.backend_status_label.setText("后端状态：关闭中...")
        self.backend_status_label.setStyleSheet("color: #ffc107;")
        self.status_bar.showMessage("正在关闭后端服务...")
        self.append_log("INFO 开始关闭后端进程...")

        # 停止健康检查线程
        if self.health_thread and self.health_thread.isRunning():
            self.health_thread.stop()

        # 停止日志读取线程
        if self.log_thread and self.log_thread.isRunning():
            self.log_thread.stop()

        # 启动异步进程终止线程
        self.termination_thread = ProcessTerminationThread(self.app_pid, self.app_process)
        self.termination_thread.termination_finished.connect(self.onTerminationFinished)
        self.termination_thread.start()

    def onTerminationFinished(self, process_terminated, message):
        """进程终止完成后的回调"""
        self.append_log(f"INFO {message}")

        # 重置状态
        self.is_app_running = False
        self.is_scanning = False
        self.app_process = None
        self.app_pid = None

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

    def is_port_in_use(self, port):
        """检查端口是否被占用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0

    def cleanup_port(self, port):
        """清理端口占用"""
        cleaned = False
        if PSUTIL_WORKING:
            try:
                for conn in psutil.net_connections(kind='inet'):
                    if conn.laddr.port == port and conn.status == 'LISTEN':
                        try:
                            process = psutil.Process(conn.pid)
                            process.terminate()
                            process.wait(timeout=1)
                            self.append_log(f"INFO 已清理占用端口{port}的进程")
                            cleaned = True
                        except:
                            continue
            except:
                pass
        return cleaned

    def updateUIForRunningState(self, state):
        """更新UI为运行状态"""
        self.toggle_app_btn.setText(f"关闭 app.py 后端 ({state})")
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
        self.toggle_app_btn.setDisabled(False)

    def resetUIAfterFailure(self):
        """启动失败后重置UI"""
        self.toggle_app_btn.setDisabled(False)
        self.toggle_app_btn.setText("启动 app.py 后端")
        self.backend_status_label.setText("后端状态：启动失败")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.status_bar.showMessage("启动失败，请检查日志")

    def startAPIHealthCheck(self):
        self.health_thread = APIHealthCheckThread(self.api_health_url)
        self.health_thread.health_result.connect(self.updateHealthStatus)
        self.health_thread.start()

    def updateHealthStatus(self, health_data):
        # 1. 同步后端运行状态 - 修改逻辑
        # 如果健康检查能返回数据，说明后端在运行，无论health_data中的值是什么
        if self.is_app_running:
            self.backend_status_label.setText("后端状态：运行中")
            self.backend_status_label.setStyleSheet("color: #28a745;")
        else:
            self.backend_status_label.setText("后端状态：未启动")
            self.backend_status_label.setStyleSheet("color: #dc3545;")

        # 2. 同步扫描状态
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

        # 3. 同步数据库状态
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

        # 4. 同步状态栏
        self.status_bar.showMessage(f"系统状态：{health_data.get('message', '未知状态')}")

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
            # 用户确认
            reply = QMessageBox.question(
                self, '确认关闭',
                '后端服务正在运行，确定要关闭吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            
            if reply == QMessageBox.Yes:
                self.stopApp()
                # 等待进程终止
                for _ in range(10):  # 最多等待5秒
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
