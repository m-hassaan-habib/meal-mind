from flask import g
import pymysql
import config

def get_db():
    if 'db' not in g:
        g.db = pymysql.connect(host=config.DB_HOST, port=config.DB_PORT, user=config.DB_USER, password=config.DB_PASS, database=config.DB_NAME, cursorclass=pymysql.cursors.DictCursor, autocommit=True)
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def query(sql, params=None, one=False):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params or ())
        if cur.description:
            rows = cur.fetchall()
            return (rows[0] if rows else None) if one else rows
        return None

def execute(sql, params=None):
    db = get_db()
    with db.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.lastrowid
