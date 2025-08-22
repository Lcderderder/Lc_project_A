import os
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime

# ȷ����־Ŀ¼����
LOG_DIR = "crash_reports"
os.makedirs(LOG_DIR, exist_ok=True)

# ��־�ļ������������ڣ�
LOG_FILENAME = os.path.join(LOG_DIR, f"app_{datetime.now().strftime('%Y%m%d')}.log")

def setup_logger(name=__name__):
    """������־��¼����������ļ��Ϳ���̨"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.ERROR)  # ֻ��¼���󼶱�����

    # �����ظ�����
    if logger.handlers:
        return logger

    # ��־��ʽ
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(module)s:%(lineno)d - %(message)s'
    )

    # �ļ�����������ת��־�����5���ļ���ÿ��1MB��
    file_handler = RotatingFileHandler(
        LOG_FILENAME,
        maxBytes=1024 * 1024,  # 1MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.ERROR)

    # ����̨������
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.ERROR)

    # ��Ӵ�����
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger