"""Acceso a datos: SQLite para desarrollo y pruebas, PostgreSQL en producción."""
import sqlite3
from contextlib import contextmanager

TABLAS = [
    """CREATE TABLE IF NOT EXISTS usuarios(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT NOT NULL UNIQUE,
        nombre TEXT NOT NULL,
        rol TEXT NOT NULL,
        clave TEXT NOT NULL,
        activo INTEGER NOT NULL DEFAULT 1,
        sv INTEGER NOT NULL DEFAULT 0,
        creado TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS registros(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        coleccion TEXT NOT NULL,
        datos TEXT NOT NULL,
        ver INTEGER NOT NULL DEFAULT 1)""",
    "CREATE INDEX IF NOT EXISTS ix_registros_col ON registros(coleccion)",
    "CREATE TABLE IF NOT EXISTS contador(id INTEGER PRIMARY KEY, valor INTEGER NOT NULL)",
    """CREATE TABLE IF NOT EXISTS bloques(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        desde INTEGER NOT NULL,
        hasta INTEGER NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS auditoria(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        usuario TEXT,
        rol TEXT,
        accion TEXT NOT NULL,
        coleccion TEXT,
        rid INTEGER,
        detalle TEXT)""",
]


class Tx:
    def __init__(self, con, pg):
        self.con, self.pg = con, pg

    def _q(self, sql):
        return sql.replace("?", "%s") if self.pg else sql

    def filas(self, sql, p=()):
        return [dict(r) for r in self.con.execute(self._q(sql), tuple(p)).fetchall()]

    def una(self, sql, p=()):
        f = self.filas(sql, p)
        return f[0] if f else None

    def ejecutar(self, sql, p=()):
        self.con.execute(self._q(sql), tuple(p))

    def insertar(self, sql, p=()):
        if self.pg:
            return self.con.execute(self._q(sql) + " RETURNING id", tuple(p)).fetchone()["id"]
        return self.con.execute(sql, tuple(p)).lastrowid


class BD:
    def __init__(self, url):
        self.pg = url.startswith(("postgres://", "postgresql://"))
        self.url = url
        self.ruta = None if self.pg else url.replace("sqlite:///", "", 1)
        with self.tx() as t:
            for ddl in TABLAS:
                t.ejecutar(ddl.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY") if self.pg else ddl)
            if not t.una("SELECT 1 AS x FROM contador"):
                t.ejecutar("INSERT INTO contador(id,valor) SELECT 1, COALESCE(MAX(id),0) FROM registros")

    @contextmanager
    def tx(self, escritura=True):
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            con = psycopg.connect(self.url, row_factory=dict_row)
        else:
            con = sqlite3.connect(self.ruta, timeout=15, isolation_level=None)
            con.row_factory = sqlite3.Row
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("BEGIN IMMEDIATE" if escritura else "BEGIN")
        try:
            yield Tx(con, self.pg)
            con.commit() if self.pg else con.execute("COMMIT")
        except BaseException:
            try:
                con.rollback() if self.pg else con.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            con.close()
