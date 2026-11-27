"""
数据库连接配置
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings
from sqlalchemy import text


# 异步数据库引擎
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
)

# 异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""
    pass


async def get_db() -> AsyncSession:
    """获取数据库会话（依赖注入用）"""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db():
    """初始化数据库（创建表 + 自动迁移缺失列）"""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL;"))
        await conn.run_sync(Base.metadata.create_all)

        # 自动迁移：为已有表添加缺失的列
        for table in Base.metadata.sorted_tables:
            # 获取数据库中该表的现有列名
            result = await conn.execute(text(f"PRAGMA table_info('{table.name}')"))
            existing_columns = {row[1] for row in result.fetchall()}

            # 对比模型中定义的列，添加缺失的
            for column in table.columns:
                if column.name not in existing_columns:
                    col_type = column.type.compile(dialect=engine.dialect)
                    nullable = "" if column.nullable else " NOT NULL DEFAULT ''"
                    alter_sql = f"ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}{nullable}"
                    try:
                        await conn.execute(text(alter_sql))
                        print(f"数据库迁移: 为 {table.name} 添加列 {column.name} ({col_type})")
                    except Exception as e:
                        print(f"数据库迁移跳过 {table.name}.{column.name}: {e}")
