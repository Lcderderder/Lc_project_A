import os
import sys
import time
import json
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QLabel, QPushButton, QTextEdit, QMessageBox, QStatusBar, QProgressBar)
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
        self.previous_health_status = None  # 记录上一次健康状态（避免重复日志）
        self.db_ready = False  # 新增：标记数据库是否就绪（核心控制变量）
        self.db_poll_timer = None  # 新增：数据库就绪轮询定时器（替代提前启动的健康定时器）
        self.network_manager = QNetworkAccessManager()
        self.network_manager.finished.connect(self.handle_health_response)

        self.stopping = False          # 正在停止标志
        self._inflight_replies = []    # 在途健康检查请求
        self.termination_finalized = False
        
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

        # 后端状态和健康监测状态放在同一行（整体居中）
        backend_status_widget = QWidget()
        backend_status_layout = QHBoxLayout(backend_status_widget)
        backend_status_layout.setContentsMargins(0, 0, 0, 0)
        backend_status_layout.setAlignment(Qt.AlignCenter)  # 整体居中
        
        self.backend_status_label = QLabel("后端状态：未启动")
        self.backend_status_label.setFont(QFont("微软雅黑", 14, QFont.Bold))
        self.backend_status_label.setStyleSheet("color: #dc3545;")
        backend_status_layout.addWidget(self.backend_status_label)
        
        # 健康监测状态标签（与后端状态同行，增加间距）
        self.health_status_label = QLabel("")
        self.health_status_label.setFont(QFont("微软雅黑", 10))
        self.health_status_label.setContentsMargins(15, 0, 0, 0)
        backend_status_layout.addWidget(self.health_status_label)
        
        status_layout.addWidget(backend_status_widget)

        self.scan_status_label = QLabel("扫描状态：未开始")
        self.scan_status_label.setFont(QFont("微软雅黑", 12))
        self.scan_status_label.setAlignment(Qt.AlignCenter)
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        status_layout.addWidget(self.scan_status_label)

        # 扫描进度条
        self.scan_progress_bar = QProgressBar()
        self.scan_progress_bar.setRange(0, 100)
        self.scan_progress_bar.setTextVisible(True)
        self.scan_progress_bar.setFormat("扫描进度: %p%")
        self.scan_progress_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #ccc;
                border-radius: 5px;
                text-align: center;
                background-color: #f8f9fa;
                height: 20px;
            }
            QProgressBar::chunk {
                background-color: #28a745;
                border-radius: 4px;
            }
        """)
        status_layout.addWidget(self.scan_progress_bar)
        
        # 扫描进度文本
        self.scan_progress_text = QLabel("等待扫描开始...")
        self.scan_progress_text.setFont(QFont("微软雅黑", 10))
        self.scan_progress_text.setAlignment(Qt.AlignCenter)
        status_layout.addWidget(self.scan_progress_text)

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
        
        # 健康检查定时器（仅数据库就绪后启动）
        self.health_timer = QTimer()
        self.health_timer.timeout.connect(self.check_health_async)
        self.health_timer.setInterval(3000)  # 3秒一次持续监测
        
        # 初始化进度条为隐藏状态
        self.scan_progress_bar.setVisible(False)
        self.scan_progress_text.setVisible(False)
    
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
            self.append_log("[INFO] 正在清理端口...")
            self.cleanup_port(5000)
            
            self.append_log("[INFO] 正在启动后端服务...")
            
            # 重置所有状态（关键：数据库就绪状态重置为False）
            self.last_health_status = None
            self.consecutive_failures = 0
            self.previous_health_status = None
            self.db_ready = False  # 初始化为未就绪
            if self.db_poll_timer:  # 防止定时器残留
                self.db_poll_timer.stop()
                self.db_poll_timer = None
            
            # 使用QProcess启动后端
            self.app_process = QProcess()
            self.app_process.setProcessChannelMode(QProcess.MergedChannels)
            
            # 连接信号
            self.app_process.readyReadStandardOutput.connect(self.handle_process_output)
            self.app_process.finished.connect(self.handle_process_finished)
            self.app_process.errorOccurred.connect(self.handle_process_error)
            
            # 启动进程
            self.app_process.start(sys.executable, ["app.py"])
            
            # 等待进程启动（5秒超时）
            if not self.app_process.waitForStarted(5000):
                raise Exception("进程启动超时")
                
            self.is_app_running = True
            
            # 更新UI：后端启动中，健康监测显示"等待数据库就绪"
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
            self.health_status_label.setText("[等待数据库就绪...]")  # 过渡状态提示
            self.health_status_label.setStyleSheet("color: #ffc107;")  # 黄色过渡色
            self.status_bar.showMessage("后端启动中，等待数据库就绪...")
            
            # 关键修改：启动「数据库就绪轮询」（2秒一次，替代直接启动健康监测）
            QTimer.singleShot(2000, self.start_db_polling)

        except Exception as e:
            self.append_log(f"ERROR 启动失败: {str(e)}")
            self.resetUIAfterFailure()
    
    def start_db_polling(self):
        """新增：启动数据库就绪轮询（2秒一次，直到数据库就绪）"""
        if not self.is_app_running:
            return
            
        # 初始化轮询定时器（2秒一次，避免频繁请求）
        self.db_poll_timer = QTimer()
        self.db_poll_timer.timeout.connect(self.check_db_ready_once)  # 单次健康检查（仅判断数据库）
        self.db_poll_timer.setInterval(2000)
        self.db_poll_timer.start()
        
        # 同时设置数据库就绪超时（60秒，避免无限等待）
        self.db_ready_timeout = QTimer()
        self.db_ready_timeout.timeout.connect(self.handle_db_ready_timeout)
        self.db_ready_timeout.setSingleShot(True)
        self.db_ready_timeout.start(60000)  # 60秒超时
        
        # 首次主动触发一次轮询
        self.check_db_ready_once()
    
    def check_db_ready_once(self):
        if self.stopping or not self.is_app_running or self.db_ready:
            return
        try:
            url = QUrl("http://localhost:5000/api/health")
            request = QNetworkRequest(url)
            request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
            request.setHeader(QNetworkRequest.UserAgentHeader, "PhotoManager/1.0")

            reply = self.network_manager.get(request)                 # ✅ 接住
            self._inflight_replies.append(reply)                      # ✅ 记录
            reply.finished.connect(lambda r=reply: self._cleanup_reply(r))  # ✅ 回收
        except Exception as e:
            self.append_log(f"WARN 数据库轮询请求失败: {str(e)}")

    
    def handle_db_ready_timeout(self):
        """新增：数据库就绪超时处理（60秒未就绪提示错误）"""
        if not self.db_ready and self.is_app_running:
            self.append_log("ERROR 数据库就绪超时（60秒），请检查后端服务")
            self.health_status_label.setText("[数据库就绪超时 ✗]")
            self.health_status_label.setStyleSheet("color: #dc3545;")
            self.status_bar.showMessage("数据库就绪超时，健康监测未启动")
            # 停止轮询
            if self.db_poll_timer:
                self.db_poll_timer.stop()
                self.db_poll_timer = None
    
    def handle_health_check_timeout(self):
        """健康检查超时处理（仅数据库就绪后生效）"""
        if not self.last_health_status and self.db_ready:
            self.append_log("ERROR 健康监测超时，请检查后端服务")
            self.health_status_label.setText("[健康监测超时 ✗]")
            self.health_status_label.setStyleSheet("color: #dc3545;")
    
    def stopApp(self):
        """关闭后端：先停健康检查与在途请求，再优雅终止进程"""
        if not self.is_app_running or not self.app_process:
            return

        # 标记正在停止：后续回调、网络响应不再当错误处理
        self.stopping = True
        self.termination_finalized = False

        # UI 反馈：按钮禁用 + 提示文案
        self.append_log("[INFO] 正在关闭后端服务...")
        self.toggle_app_btn.setDisabled(True)
        self.toggle_app_btn.setText("关闭中...")

        # ① 先停所有健康检查相关定时器/轮询
        try:
            self.health_timer.stop()
        except Exception:
            pass
        try:
            if self.db_poll_timer:
                self.db_poll_timer.stop()
                self.db_poll_timer = None
        except Exception:
            pass
        try:
            if hasattr(self, 'db_ready_timeout'):
                self.db_ready_timeout.stop()
        except Exception:
            pass
        try:
            if hasattr(self, 'health_check_timeout'):
                self.health_check_timeout.stop()
        except Exception:
            pass

        # ② 中止所有在途网络请求，防止回调继续刷日志
        try:
            for r in list(self._inflight_replies):
                try:
                    r.abort()
                except Exception:
                    pass
            self._inflight_replies.clear()
            try:
                self.network_manager.clearAccessCache()
            except Exception:
                pass
        except Exception:
            pass

        # ③ 重置状态（健康/数据库/扫描等），静音UI
        self.last_health_status = None
        self.consecutive_failures = 0
        self.previous_health_status = None
        self.db_ready = False

        try:
            self.scan_progress_bar.setVisible(False)
            self.scan_progress_text.setVisible(False)
            self.scan_status_label.setText("扫描状态：未开始")
            self.scan_status_label.setStyleSheet("color: #ffc107;")
            self.db_status_label.setText("数据库状态：未就绪")
            self.db_status_label.setStyleSheet("color: #ffc107;")
            self.health_status_label.setText("")  # 清空健康状态
        except Exception:
            pass

        # ④ 最后异步终止进程（先 terminate，必要时 kill）
        QTimer.singleShot(0, self.terminate_process_async)

    
    def terminate_process_async(self):
        """异步终止进程"""
        try:
            if self.app_process and self.app_process.state() == QProcess.Running:
                # 先尝试正常终止
                self.app_process.terminate()
                # 2秒超时后强制杀死
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
            # ❌ 不要直接调用 on_termination_complete()
            # ✅ 兜底：若短时间内仍未触发 finished，则手动收尾一次
            QTimer.singleShot(200, self._finalize_if_needed)
        except Exception as e:
            self.append_log(f"ERROR 强制终止失败: {str(e)}")
            self._finalize_if_needed()

    def _finalize_if_needed(self):
        """兜底收尾：仅当还未收尾且进程已不在运行时触发"""
        if not self.termination_finalized and (not self.app_process or self.app_process.state() != QProcess.Running):
            self.on_termination_complete()
    
    def on_termination_complete(self):
        """进程终止完成"""
        if self.termination_finalized:
            return                      
        self.termination_finalized = True
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
        self.health_status_label.setText("")  # 清空健康状态
        self.scan_status_label.setText("扫描状态：未开始")
        self.scan_status_label.setStyleSheet("color: #ffc107;")
        self.db_status_label.setText("数据库状态：未就绪")
        self.db_status_label.setStyleSheet("color: #ffc107;")
        
        self.status_bar.showMessage("后端已关闭")
        self.append_log("[INFO] 后端服务已关闭")
        
        # 清理进程对象
        if self.app_process:
            self.app_process.deleteLater()
            self.app_process = None
        
        # 如果用户请求关闭窗口，现在可以关闭了
        if self.user_requested_close:
            self.user_requested_close = False
            QTimer.singleShot(0, self.close)

        self.stopping = False
    
    def handle_process_output(self):
        """处理进程输出（新增过滤逻辑）"""
        if self.app_process:
            data = self.app_process.readAllStandardOutput().data()
            try:
                text = data.decode('utf-8').strip()
            except UnicodeDecodeError:
                try:
                    text = data.decode('gbk', errors='replace').strip()
                except:
                    text = f"[无法解码的日志: {data.hex()}]"
            
            # 修改过滤逻辑：只过滤健康检查相关的日志，保留扫描日志
            if text and ("GET /api/health HTTP/1.1" not in text and 
                        "Health check" not in text and  # 添加更多可能需要过滤的关键词
                        "127.0.0.1" not in text):  # 过滤IP地址日志
                self.process_output.emit(text)
    
    def handle_process_finished(self, code, status):
        if self.stopping:
            # 停止阶段视为正常退出，不打 WARN
            self.append_log("[INFO] 后端进程已退出")
        else:
            self.append_log(f"WARN 进程异常退出，代码: {code}")
        if not self.termination_finalized:
            self.on_termination_complete()

    def handle_process_error(self, error):
        """进程错误回调"""
        if self.stopping:
            # 停止阶段忽略错误（不打印 ERROR，避免扰民）
            return
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
        if self.stopping or not self.is_app_running or not self.db_ready:
            return
        try:
            url = QUrl("http://localhost:5000/api/health")
            request = QNetworkRequest(url)
            request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
            request.setHeader(QNetworkRequest.UserAgentHeader, "PhotoManager/1.0")

            reply = self.network_manager.get(request)                 # ✅ 接住
            self._inflight_replies.append(reply)                      # ✅ 记录
            reply.finished.connect(lambda r=reply: self._cleanup_reply(r))  # ✅ 回收
        except Exception as e:
            if not self.last_health_status or self.last_health_status.get('status') != 'unhealthy':
                self.append_log(f"WARN 健康检查请求失败: {str(e)}")
            if self.last_health_status:
                self.health_check_result.emit(self.last_health_status)
            else:
                self.health_check_result.emit({
                    'status': 'unhealthy',
                    'scan_finished': True,
                    'db_ready': self.db_ready,
                    'message': '健康检查初始化失败'
                })

    def _cleanup_reply(self, reply):
        try:
            if reply in self._inflight_replies:
                self._inflight_replies.remove(reply)
            reply.deleteLater()
        except Exception:
            pass
    
    def handle_health_response(self, reply):
        """处理健康检查响应（核心：判断数据库是否就绪，决定是否启动持续监测）"""
        if self.stopping or not self.is_app_running:
            reply.deleteLater()
            return
        try:
            if reply.error() == QNetworkReply.NoError:
                data = reply.readAll().data()
                try:
                    health_data = json.loads(data.decode('utf-8'))
                    self.last_health_status = health_data
                    self.consecutive_failures = 0
                    
                    # 关键判断：数据库是否从"未就绪"变为"就绪"
                    new_db_ready = health_data.get("db_ready", False)
                    if not self.db_ready and new_db_ready:
                        self.db_ready = True  # 标记数据库已就绪
                        self.append_log("[INFO] 数据库已就绪，启动持续健康监测")
                        # 停止数据库轮询，启动持续健康监测
                        if self.db_poll_timer:
                            self.db_poll_timer.stop()
                            self.db_poll_timer = None
                        if hasattr(self, 'db_ready_timeout'):
                            self.db_ready_timeout.stop()
                        # 启动持续健康监测（3秒一次）
                        self.health_timer.start()
                        # 启动健康监测超时（30秒）
                        self.health_check_timeout = QTimer()
                        self.health_check_timeout.timeout.connect(self.handle_health_check_timeout)
                        self.health_check_timeout.setSingleShot(True)
                        self.health_check_timeout.start(30000)
                    
                    # 传递健康数据更新UI
                    self.health_check_result.emit(health_data)
                except Exception as e:
                    # 解析失败时，用最后一次有效状态
                    if self.last_health_status:
                        self.health_check_result.emit(self.last_health_status)
                    else:
                        self.health_check_result.emit({
                            'status': 'unhealthy',
                            'scan_finished': True,
                            'db_ready': self.db_ready,
                            'message': '解析健康响应失败'
                        })
                    # 仅首次解析失败输出日志
                    if not self.previous_health_status or self.previous_health_status != 'unhealthy':
                        self.append_log(f"ERROR 解析健康响应失败: {str(e)}")
            else:
                # 网络错误：保持最后一次健康状态
                self.consecutive_failures += 1
                if self.consecutive_failures == 1 or self.consecutive_failures > 3:
                    self.append_log(f"WARN 健康检查网络错误: {reply.errorString()}")
                # 用最后一次有效状态更新UI
                if self.last_health_status:
                    self.health_check_result.emit(self.last_health_status)
                else:
                    self.health_check_result.emit({
                        'status': 'unhealthy',
                        'scan_finished': True,
                        'db_ready': self.db_ready,  # 保留当前数据库状态
                        'message': f'网络错误: {reply.errorString()}'
                    })
        finally:
            reply.deleteLater()
    
    def update_health_status(self, health_data):
        """更新健康状态UI（根据数据库就绪状态调整显示）"""
        # 1. 健康状态日志：仅状态变化时输出
        current_status = health_data.get('status', 'unknown')
        if current_status != self.previous_health_status:
            self.append_log(f"[INFO] 健康状态更新: {current_status} - {health_data.get('message', '无描述')}")
            self.previous_health_status = current_status
        
        # 2. 健康状态标签：区分「数据库未就绪」「就绪后监测」两种状态
        if not self.db_ready:
            # 数据库未就绪：显示轮询状态
            self.health_status_label.setText("[等待数据库就绪...]")
            self.health_status_label.setStyleSheet("color: #ffc107;")
        else:
            # 数据库就绪：显示正常健康监测状态
            if health_data.get('status') == 'healthy':
                self.health_status_label.setText("[健康监测中 ✓]")
                self.health_status_label.setStyleSheet("color: #28a745;")  # 绿色
            else:
                self.health_status_label.setText("[健康监测错误 ✗]")
                self.health_status_label.setStyleSheet("color: #dc3545;")  # 红色
        
        # 3. 后端状态：仅状态变化时更新
        new_backend_text = "后端状态：运行中" if self.is_app_running else "后端状态：未启动"
        new_backend_style = "color: #28a745;" if self.is_app_running else "color: #dc3545;"
        if self.backend_status_label.text() != new_backend_text:
            self.backend_status_label.setText(new_backend_text)
            self.backend_status_label.setStyleSheet(new_backend_style)

        # 4. 扫描状态：仅数据库就绪后更新
        if self.db_ready:
            current_scan_finished = health_data.get("scan_finished", True)
            self.is_scanning = not current_scan_finished
            if self.is_scanning:
                new_scan_text = "扫描状态：自动执行中..."
                new_scan_style = "color: #ffc107;"
                # 显示进度条
                self.scan_progress_bar.setVisible(True)
                self.scan_progress_text.setVisible(True)
                
                # 进度条数值变化时更新
                scan_progress = health_data.get("scan_progress", {})
                total = scan_progress.get("total", 0)
                processed = scan_progress.get("processed", 0)
                current_progress = int((processed / total) * 100) if total > 0 else 0
                current_progress_text = f"扫描进度: {processed}/{total} 张照片" if total > 0 else "正在统计照片数量..."
                
                if self.scan_progress_bar.value() != current_progress:
                    self.scan_progress_bar.setValue(current_progress)
                if self.scan_progress_text.text() != current_progress_text:
                    self.scan_progress_text.setText(current_progress_text)
            else:
                new_scan_text = "扫描状态：已完成"
                new_scan_style = "color: #28a745;"
                # 隐藏进度条
                self.scan_progress_bar.setVisible(False)
                self.scan_progress_text.setVisible(False)
            
            if self.scan_status_label.text() != new_scan_text:
                self.scan_status_label.setText(new_scan_text)
                self.scan_status_label.setStyleSheet(new_scan_style)

        # 5. 数据库状态：根据健康数据更新
        current_db_ready = health_data.get("db_ready", False)
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
        
        if self.db_status_label.text() != new_db_text:
            self.db_status_label.setText(new_db_text)
            self.db_status_label.setStyleSheet(new_db_style)

        # 6. 状态栏：区分数据库就绪前后的提示
        if self.db_ready:
            self.status_bar.showMessage(f"系统状态：{health_data.get('message', '未知状态')}")
        else:
            self.status_bar.showMessage("后端启动中，等待数据库就绪...")
    
    def cleanup_port(self, port):
        """清理端口占用 - 异步执行"""
        try:
            import subprocess
            if os.name == 'nt':  # Windows
                cmd = (
                    f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{port} ^| findstr LISTENING\') do '
                    f'@taskkill /F /PID %a >nul 2>&1'
                )
                subprocess.Popen(cmd, shell=True,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:  # Unix/Linux/Mac
                subprocess.Popen(
                    f'lsof -ti:{port} | xargs -r kill -9',
                    shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
        except Exception:
            pass
    
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
        self.health_status_label.setText("")
        self.status_bar.showMessage("启动失败，请检查日志")
    
    def closeEvent(self, event):
        # 如果后端正在运行，先停止后端
        if self.is_app_running:
            self.user_requested_close = True
            self.stopApp()
            event.ignore()
            return
        
        # 停止所有定时器
        self.health_timer.stop()
        if self.db_poll_timer:
            self.db_poll_timer.stop()
        
        event.accept()

def main():
    app = QApplication(sys.argv)
    manager = PhotoBackendManager()
    manager.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()