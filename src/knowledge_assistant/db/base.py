"""SQLAlchemy 声明式模型的公共基类。"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """集中保存所有 ORM 模型的表结构元数据。"""

