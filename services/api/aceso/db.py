from psycopg_pool import ConnectionPool
from aceso.config import settings

pool = ConnectionPool(settings.database_url, open=False)

def get_db():
    with pool.connection() as conn:
        yield conn
