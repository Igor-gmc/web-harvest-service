from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"ssl": "disable"},
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
