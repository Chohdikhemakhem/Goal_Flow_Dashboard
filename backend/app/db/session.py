from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import get_settings

settings = get_settings()
is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if is_sqlite else {}

# pool_size/max_overflow n'ont pas de sens pour SQLite (pas de vrai pool
# de connexions concurrentes), donc on ne les applique que pour les
# bases reseau (PostgreSQL, etc.).
#
# Dimensionnement cible : 8 workers Uvicorn x (pool_size + max_overflow)
# = 8 x 10 = 80 connexions max, sous le plafond Postgres actuel de 100
# (max_connections), avec 20 de marge pour Adminer / outils d'admin.
# Si le nombre de workers change, recalculer en consequence.
engine_kwargs = {"pool_pre_ping": True, "connect_args": connect_args}
if not is_sqlite:
    engine_kwargs.update(pool_size=8, max_overflow=2)

engine = create_engine(settings.database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()