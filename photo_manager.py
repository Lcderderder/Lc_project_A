import sys
import os
import subprocess
import time
import requests
import psutil
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QPushButton, QLabel, QStatusBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QIcon, QColor
from logger import setup_logger
from config import Config

# 初始化日志器
logger = setup_logger(__name__)

# ------------------------------
# API健康检测线程
# ------------------------------
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
                error_msg = f"健康检测错误：{str(e)}"
                logger.error(error_msg)
                self.health_result.emit({
                    "backend_running": False,
                    "db_ready": False,
                    "scan_finished": False,
                    "message": f"检测错误：{str(e)[:15]}"
                })
            time.sleep(2)

    def stop(self):
        self.running = False

# ------------------------------
# 主管理窗口
# ------------------------------
class PhotoBackendManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.api_health_url = f"{Config.API_URL}health"
        self.app_process = None
        self.app_pid = None
        self.is_app_running = False  # 后端是否启动
        self.is_scanning = False     # 是否正在扫描（同步后端状态）
        self.health_thread = None
        self.initUI()
        self.centerWindow()

    def initUI(self):
        # 窗口基础设置
        self.setWindowTitle("Lc照相馆 - 后端管理（自动扫描）")
        self.setGeometry(100, 100, 480, 300)
        icon_path = 'camera_icon.png'
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        else:
            self.setWindowIcon(QIcon.fromTheme("system-run"))

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)

        # 状态显示区
        status_group = QWidget()
        status_layout = QVBoxLayout(status_group)
        status_layout.setSpacing(12)

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

        # 核心按钮（初始状态：可启动）
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

        # 状态栏（不变）
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪 - 启动后端后将自动扫描并创建数据库")

    # 窗口居中（不变）
    def centerWindow(self):
        screen_geo = QApplication.primaryScreen().availableGeometry()
        window_geo = self.frameGeometry()
        window_geo.moveCenter(screen_geo.center())
        self.move(window_geo.topLeft())

    # 启停app.py（根据扫描状态控制按钮）
    def toggleApp(self):
        if not self.is_app_running:
            self.startApp()
        else:
            # 即使扫描中，也允许关闭后端（强制终止）
            self.stopApp()

    # 启动app.py（不变）
    def startApp(self):
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("启动中...")
        self.backend_status_label.setText("后端状态：启动中...")
        self.backend_status_label.setStyleSheet("color: #ffc107;")
        self.scan_status_label.setText("扫描状态：等待后端启动...")
        self.status_bar.showMessage("正在启动 app.py 后端...")

        try:
            project_dir = os.path.dirname(os.path.abspath(__file__))
            app_path = os.path.join(project_dir, "app.py")
            if not os.path.exists(app_path):
                raise FileNotFoundError(f"未找到 app.py（{app_path}）")

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            self.app_process = subprocess.Popen(
                [sys.executable, "app.py"],
                cwd=project_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo
            )

            self.app_pid = self.app_process.pid
            print(f"后端进程启动，PID：{self.app_pid}")

            time.sleep(1)
            if self.app_process.poll() is None:
                self.is_app_running = True
                self.is_scanning = True  # 初始标记为扫描中
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
                # 启动后立即启用关闭按钮（即使扫描中也允许关闭）
                self.toggle_app_btn.setDisabled(False)
            else:
                _, err = self.app_process.communicate()
                err_msg = err.decode("utf-8", errors="ignore")[:30]
                raise Exception(f"启动失败：{err_msg}")

        except Exception as e:
            error_msg = f"启动后端失败：{str(e)}"
            logger.error(error_msg)
            self.toggle_app_btn.setDisabled(False)
            self.toggle_app_btn.setText("启动 app.py 后端（自动扫描）")
            self.backend_status_label.setText("后端状态：启动失败")
            self.backend_status_label.setStyleSheet("color: #dc3545;")
            self.status_bar.showMessage(f"错误：{str(e)}")
            self.app_pid = None
            self.app_process = None

    # 关闭app.py（不变，强制终止）
    def stopApp(self):
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("关闭中...")
        self.backend_status_label.setText("后端状态：关闭中...")
        self.backend_status_label.setStyleSheet("color: #ffc107;")
        self.status_bar.showMessage("正在关闭 app.py 后端...")

        # 停止API检测线程
        if self.health_thread and self.health_thread.isRunning():
            self.health_thread.stop()
            self.health_thread.wait()

        # 强制终止进程
        if self.app_pid:
            try:
                parent_process = psutil.Process(self.app_pid)
                child_processes = parent_process.children(recursive=True)
                for child in child_processes:
                    try:
                        child.terminate()
                        child.wait(timeout=2)
                        print(f"已终止子进程，PID：{child.pid}")
                    except Exception as e:
                        print(f"终止子进程PID {child.pid} 失败：{e}")
                parent_process.terminate()
                parent_process.wait(timeout=3)
                if not psutil.pid_exists(self.app_pid):
                    self.status_bar.showMessage("后端进程已成功终止")
                else:
                    parent_process.kill()
                    print(f"强制终止后端进程，PID：{self.app_pid}")
                    self.status_bar.showMessage("后端进程已强制终止")
            except psutil.NoSuchProcess:
                self.status_bar.showMessage("后端进程已不存在")
            except Exception as e:
                error_msg = f"终止进程失败：{str(e)}"
                logger.error(error_msg)
                self.status_bar.showMessage(f"终止进程失败：{str(e)[:20]}")
        else:
            if self.app_process:
                self.app_process.terminate()
                self.app_process.wait()
                self.app_process = None

        # 重置状态
        self.is_app_running = False
        self.is_scanning = False
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

    # 启动API检测（不变）
    def startAPIHealthCheck(self):
        self.health_thread = APIHealthCheckThread(self.api_health_url)
        self.health_thread.health_result.connect(self.updateHealthStatus)
        self.health_thread.start()

    # 【核心修复】更新状态时同步按钮禁用状态
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
            self.toggle_app_btn.setDisabled(False)  # 异常停止后允许重新启动

        # 2. 同步扫描状态（关键：控制按钮文本和禁用）
        self.is_scanning = not health_data["scan_finished"]
        if self.is_app_running:
            if self.is_scanning:
                # 扫描中：按钮显示“关闭（扫描中）”，允许点击（强制关闭）
                self.toggle_app_btn.setText("关闭 app.py 后端（扫描中）")
                self.toggle_app_btn.setDisabled(False)
                self.scan_status_label.setText("扫描状态：自动执行中...")
                self.scan_status_label.setStyleSheet("color: #ffc107;")
            else:
                # 扫描完成：按钮显示“关闭后端”，允许点击
                self.toggle_app_btn.setText("关闭 app.py 后端")
                self.toggle_app_btn.setDisabled(False)
                self.scan_status_label.setText("扫描状态：已完成")
                self.scan_status_label.setStyleSheet("color: #28a745;")
        else:
            # 后端未运行：按钮显示“启动后端”
            self.toggle_app_btn.setText("启动 app.py 后端（自动扫描）")

        # 3. 同步数据库状态（不变）
        if health_data["db_ready"]:
            if "共" in health_data["message"] and "张照片" in health_data["message"]:
                photo_count = health_data["message"].split("共")[1].split("张照片")[0]
                self.db_status_label.setText(f"数据库状态：已就绪（共{photo_count}张照片）")
            else:
                self.db_status_label.setText("数据库状态：已就绪")
            self.db_status_label.setStyleSheet("color: #28a745;")
        else:
            self.db_status_label.setText("数据库状态：未就绪（扫描完成后自动就绪）")
            self.db_status_label.setStyleSheet("color: #ffc107;")

        # 4. 同步状态栏（不变）
        self.status_bar.showMessage(f"系统状态：{health_data['message']}")

    # 窗口关闭清理（不变）
    def closeEvent(self, event):
        if self.is_app_running:
            self.stopApp()
        event.accept()

# ------------------------------
# 程序入口（不变）
# ------------------------------
def main():
    try:
        import psutil
    except ImportError:
        print("错误：缺少 psutil 库，无法可靠终止后端进程！")
        print("请先执行：pip install psutil")
        sys.exit(1)
    
    app = QApplication(sys.argv)
    manager = PhotoBackendManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
