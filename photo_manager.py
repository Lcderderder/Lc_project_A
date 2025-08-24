import sys
import os
import subprocess
import time
import requests
import threading
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QStatusBar, QTextEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon

# 全局变量，标记psutil状态
HAS_PSUTIL = False
PSUTIL_WORKING = False  # 新增：psutil是否可正常工作
psutil_error = ""       # 记录psutil错误信息

try:
    import psutil
    HAS_PSUTIL = True
    # 验证psutil核心功能是否可用
    try:
        psutil.process_iter()  # 调用基础方法检测可用性
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
                res = requests.get(self.api_url, timeout=2)
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
            except Exception as e:
                self.health_result.emit({
                    "backend_running": False,
                    "db_ready": False,
                    "scan_finished": False,
                    "message": f"检测错误：{str(e)[:15]}"
                })
            time.sleep(2)

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
    """新增：异步进程终止线程"""
    termination_finished = pyqtSignal(bool, str)
    
    def __init__(self, app_pid, app_process):
        super().__init__()
        self.app_pid = app_pid
        self.app_process = app_process

    def run(self):
        process_terminated = False
        message = ""
        
        if self.app_pid and PSUTIL_WORKING:
            try:
                # 使用psutil终止进程
                process = psutil.Process(self.app_pid)
                
                # 终止所有子进程
                for child in process.children(recursive=True):
                    try:
                        child.terminate()
                    except:
                        pass
                
                # 终止主进程
                process.terminate()
                
                # 等待进程结束
                try:
                    process.wait(timeout=5)
                    process_terminated = True
                    message = "进程已关闭"
                except psutil.TimeoutExpired:
                    # 如果优雅关闭失败，使用kill()
                    for child in process.children(recursive=True):
                        try:
                            child.kill()
                        except:
                            pass
                    process.kill()
                    process.wait(timeout=3)
                    process_terminated = True
                    message = "进程已强制终止"
                    
            except psutil.NoSuchProcess:
                process_terminated = True
                message = "进程已不存在"
            except Exception as e:
                message = f"终止进程时出错: {str(e)}"
        
        elif self.app_process:
            # 如果只有process对象没有pid，使用subprocess的方法
            try:
                self.app_process.terminate()
                try:
                    self.app_process.wait(timeout=5)
                    process_terminated = True
                    message = "进程已关闭"
                except subprocess.TimeoutExpired:
                    self.app_process.kill()
                    self.app_process.wait(timeout=3)
                    process_terminated = True
                    message = "进程已强制关闭"
            except Exception as e:
                message = f"关闭进程失败: {str(e)}"
        
        self.termination_finished.emit(process_terminated, message)

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
        self.termination_thread = None  # 新增：进程终止线程
        self.initUI()
        self.centerWindow()
        
        # 检查psutil并初始化状态
        self.check_psutil()

    def check_psutil(self):
        """检查psutil是否安装且可正常工作"""
        if not HAS_PSUTIL:
            self.append_log("ERROR 未检测到psutil库，无法可靠管理进程")
            self.append_log("INFO 请执行命令安装: pip install psutil")
            self.append_log("INFO 安装后重新启动本程序")
            self._disable_backend_control("请安装psutil后使用")
        elif not PSUTIL_WORKING:
            self.append_log(f"ERROR psutil库存在但无法正常工作：{psutil_error}")
            self.append_log("INFO 可能是编译问题，建议重新安装：pip uninstall -y psutil && pip install psutil")
            self._disable_backend_control("psutil功能异常")
        else:
            self.append_log("INFO psutil库检测正常，进程管理功能可用")
            self.status_bar.showMessage("就绪 - 启动后端后将自动扫描并创建数据库")

    def _disable_backend_control(self, button_text):
        """辅助方法：禁用后端控制按钮并更新样式"""
        self.toggle_app_btn.setEnabled(False)
        self.toggle_app_btn.setText(button_text)
        self.toggle_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #6c757d;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
            }
        """)
        self.status_bar.showMessage(f"错误：psutil异常，{button_text}")

    def initUI(self):
        # 窗口基础设置
        self.setWindowTitle("Lc照相馆 - 后端管理（自动扫描）")
        self.setGeometry(100, 100, 800, 600)
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

        self.scan_status_label = QLabel("扫描状态：未开始（启动后端后自动执行）")
        self.scan_status_label.setFont(QFont("微软雅黑", 12))
        self.scan_status_label.setAlignment(Qt.AlignCenter)
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        status_layout.addWidget(self.scan_status_label)

        self.db_status_label = QLabel("数据库状态：未就绪（扫描完成后自动就绪）")
        self.db_status_label.setFont(QFont("微软雅黑", 12))
        self.db_status_label.setAlignment(Qt.AlignCenter)
        self.db_status_label.setStyleSheet("color: #ffc107;")
        status_layout.addWidget(self.db_status_label)

        main_layout.addWidget(status_group)

        # 核心按钮
        self.toggle_app_btn = QPushButton("启动 app.py 后端（自动扫描）")
        self.toggle_app_btn.setFont(QFont("微软雅黑", 12))
        self.toggle_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
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
        self.log_display.setMinimumHeight(200)
        self.log_display.setStyleSheet("""
            QTextEdit {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 10pt;
            }
        """)
        main_layout.addWidget(self.log_display)

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 - 启动后端后将自动扫描并创建数据库")

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
        if not PSUTIL_WORKING:
            self.append_log("ERROR 无法启动：psutil库不可用")
            return

        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("启动中...")
        self.backend_status_label.setText("后端状态：启动中...")
        self.backend_status_label.setStyleSheet("color: #ffc107;")
        self.scan_status_label.setText("扫描状态：等待后端启动...")
        self.status_bar.showMessage("正在启动 app.py 后端...")
        self.log_display.clear()

        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))
            app_path = os.path.join(project_dir, "app.py")
            if not os.path.exists(app_path):
                raise FileNotFoundError(f"未找到 app.py（{app_path}）")

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

            # 等待进程启动确认
            time.sleep(3)
            if self.app_process.poll() is None:
                self.is_app_running = True
                self.is_scanning = True
                self.toggle_app_btn.setText("关闭 app.py 后端（扫描中）")
                self.toggle_app_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #dc3545;
                        color: white;
                        border: none;
                        border-radius: 8px;
                        padding: 12px;
                    }
                    QPushButton:hover {
                        background-color: #bb2d3b;
                    }
                    QPushButton:disabled {
                        background-color: #6c757d;
                    }
                """)
                self.backend_status_label.setText("后端状态：运行中")
                self.backend_status_label.setStyleSheet("color: #28a745;")
                self.scan_status_label.setText("扫描状态：自动执行中...")
                self.status_bar.showMessage("后端启动成功，自动触发扫描与数据库创建...")
                self.startAPIHealthCheck()
                self.toggle_app_btn.setDisabled(False)
            else:
                # 读取进程输出
                output, _ = self.app_process.communicate()
                error_msg = output[:100] + "..." if output else "进程启动后立即退出"
                raise Exception(f"启动失败：{error_msg}")

        except Exception as e:
            error_msg = f"ERROR 启动后端失败：{str(e)}"
            self.append_log(error_msg)
            self.toggle_app_btn.setDisabled(False)
            self.toggle_app_btn.setText("启动 app.py 后端（自动扫描）")
            self.backend_status_label.setText("后端状态：启动失败")
            self.backend_status_label.setStyleSheet("color: #dc3545;")
            self.status_bar.showMessage(f"错误：{str(e)}")
            
            # 清理进程
            if self.app_process:
                try:
                    self.app_process.terminate()
                    self.app_process.wait(timeout=2)
                except:
                    pass
                self.app_process = None
            self.app_pid = None

    def stopApp(self):
        """关闭后端应用（异步方式）"""
        if not PSUTIL_WORKING:
            self.append_log("ERROR 无法关闭：psutil库不可用")
            return

        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("关闭中...")
        self.backend_status_label.setText("后端状态：关闭中...")
        self.backend_status_label.setStyleSheet("color: #ffc107;")
        self.status_bar.showMessage("正在关闭 app.py 后端...")

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
        if message:
            self.append_log(f"INFO {message}")

        # 重置状态
        self.is_app_running = False
        self.is_scanning = False
        self.app_process = None
        self.app_pid = None

        # 更新UI
        self.toggle_app_btn.setDisabled(False)
        self.toggle_app_btn.setText("启动 app.py 后端（自动扫描）")
        self.toggle_app_btn.setStyleSheet("""
            QPushButton {
                background-color: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #218838;
            }
            QPushButton:disabled {
                background-color: #6c757d;
            }
        """)
        self.backend_status_label.setText("后端状态：未启动")
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        self.scan_status_label.setText("扫描状态：未开始（启动后端后自动执行）")
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        self.db_status_label.setText("数据库状态：未就绪（扫描完成后自动就绪）")
        self.db_status_label.setStyleSheet("color: #ffc107;")
        
        if process_terminated:
            self.status_bar.showMessage("后端已成功关闭")
            self.append_log("INFO 后端服务已完全关闭")
        else:
            self.status_bar.showMessage("关闭后端时遇到问题")
            self.append_log("WARN 关闭后端时可能遇到问题")

    def startAPIHealthCheck(self):
        self.health_thread = APIHealthCheckThread(self.api_health_url)
        self.health_thread.health_result.connect(self.updateHealthStatus)
        self.health_thread.start()

    def updateHealthStatus(self, health_data):
        # 1. 同步后端运行状态
        if not health_data["backend_running"] and self.is_app_running:
            self.is_app_running = False
            self.is_scanning = False
            self.backend_status_label.setText("后端状态：已异常停止")
            self.backend_status_label.setStyleSheet("color: #dc3545;")
            self.toggle_app_btn.setText("启动 app.py 后端（自动扫描）")
            self.toggle_app_btn.setStyleSheet("""
                QPushButton {
                    background-color: #28a745;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 12px;
                }
                QPushButton:hover {
                    background-color: #218838;
                }
            """)
            self.toggle_app_btn.setDisabled(False)
            self.append_log("WARN 后端异常停止")

        # 2. 同步扫描状态
        self.is_scanning = not health_data["scan_finished"]
        if self.is_app_running:
            if self.is_scanning:
                self.toggle_app_btn.setText("关闭 app.py 后端（扫描中）")
                self.toggle_app_btn.setDisabled(False)
                self.scan_status_label.setText("扫描状态：自动执行中...")
                self.scan_status_label.setStyleSheet("color: #ffc107;")
            else:
                self.toggle_app_btn.setText("关闭 app.py 后端")
                self.toggle_app_btn.setDisabled(False)
                self.scan_status_label.setText("扫描状态：已完成")
                self.scan_status_label.setStyleSheet("color: #28a745;")
                self.append_log("INFO 扫描已完成")
        else:
            self.toggle_app_btn.setText("启动 app.py 后端（自动扫描）")

        # 3. 同步数据库状态
        if health_data["db_ready"]:
            if "共" in health_data["message"] and "张照片" in health_data["message"]:
                try:
                    photo_count = health_data["message"].split("共")[1].split("张照片")[0]
                    self.db_status_label.setText(f"数据库状态：已就绪（共{photo_count}张照片）")
                except:
                    self.db_status_label.setText("数据库状态：已就绪")
            else:
                self.db_status_label.setText("数据库状态：已就绪")
            self.db_status_label.setStyleSheet("color: #28a745;")
        else:
            self.db_status_label.setText("数据库状态：未就绪（扫描完成后自动就绪）")
            self.db_status_label.setStyleSheet("color: #ffc107;")

        # 4. 同步状态栏
        self.status_bar.showMessage(f"系统状态：{health_data['message']}")

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
            # 直接关闭后端，不弹窗确认
            self.stopApp()
        event.accept()

def main():
    app = QApplication(sys.argv)
    manager = PhotoBackendManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
