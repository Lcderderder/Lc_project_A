@echo off
chcp 65001 >nul
title 预编译库安装工具
color F0
echo ==============================
echo       预编译库安装工具
echo ==============================
echo.

echo 正在安装 psutil 预编译库...
echo 使用清华大学镜像源...
echo.

pip install psutil -i https://pypi.tuna.tsinghua.edu.cn/simple --only-binary :all:

if errorlevel 1 (
    echo.
    echo 安装失败，请检查网络连接或Python环境
) else (
    echo.
    echo psutil 预编译库安装成功！
)

echo.
echo 操作完成
echo 按任意键退出...
pause >nul