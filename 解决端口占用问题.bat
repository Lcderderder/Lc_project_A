@echo off
chcp 65001 >nul
title 端口占用处理工具
color F0
echo ==============================
echo       端口占用处理工具
echo ==============================
echo.

:: 获取用户输入的端口号
set /p port=请输入需要释放的端口号（默认5000）: 
if "%port%"=="" set port=5000

echo.
echo 正在查找端口 %port% 的占用进程...
echo.

:: 查找并处理占用进程
set "found=0"
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%port%" ^| findstr "LISTENING"') do (
    set "found=1"
    echo 发现占用进程，PID=%%a
    taskkill /F /PID %%a >nul 2>&1
    if errorlevel 1 (
        echo 终止 PID=%%a 的进程失败，请检查权限
    ) else (
        echo 已成功终止 PID=%%a 的进程
    )
)

:: 处理未找到进程的情况
if "%found%"=="0" (
    echo 未发现端口 %port% 被占用的进程
)

echo.
echo 操作完成
echo 按任意键退出...
pause >nul
