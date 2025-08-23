import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# 确保日志目录存在
LOG_DIR = "crash_reports"
os.makedirs(LOG_DIR, exist_ok=True)

# 日志文件名（包含日期）
LOG_FILENAME = os.path.join(LOG_DIR, f"app_{datetime.now().strftime('%Y%m%d')}.log")

def setup_logger(name=__name__):
    # 配置日志记录器，输出到文件和控制台
    logger = logging.getLogger(name)
    logger.setLevel(logging.ERROR)  # 只记录错误级别及以上

    # 避免重复配置
    if logger.handlers:
        return logger

    # 日志格式
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )

    # 文件处理器（轮转日志，最大5个文件，每个1MB）
    file_handler = RotatingFileHandler(
        LOG_FILENAME,
        maxBytes=1024 * 1024,  # 1MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.ERROR)

    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.ERROR)

    # 添加处理器
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger