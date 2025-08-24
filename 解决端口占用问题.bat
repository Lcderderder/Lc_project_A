@echo off
rem 查找 5000 端口并杀死占用进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5000" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a
    echo 已杀死 PID=%%a 的进程
)
rem 暂停窗口，按任意键才关闭（不加这行执行完会直接关）
pause
