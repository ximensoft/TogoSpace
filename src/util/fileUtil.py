import os

from exception import TogoException


def ensure_dir(path: str) -> None:
    """确保目录存在。若不存在则创建，创建失败时抛出 TogoException。"""
    if os.path.exists(path):
        return
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        raise TogoException(
            f"无法创建目录 '{path}': {e.strerror}",
            error_code="directory_create_failed",
        )
