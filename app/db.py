"""SQLite 持久化：多账号、转存任务、关键字规则、运行日志、去重记录。"""
import sqlite3
import json
import time
from contextlib import contextmanager
from typing import Iterable, Optional

from app.config import DB_PATH


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS accounts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                username    TEXT,
                cookies     TEXT,          -- JSON 字符串
                bdstoken    TEXT,
                is_active   INTEGER NOT NULL DEFAULT 0,
                created_at  INTEGER,
                updated_at  INTEGER
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id  INTEGER,        -- 绑定的账号
                kind        TEXT NOT NULL DEFAULT 'share',
                link        TEXT,
                pwd         TEXT,
                target_dir  TEXT NOT NULL DEFAULT '/',
                interval    TEXT NOT NULL DEFAULT 'daily',
                rename_on   INTEGER NOT NULL DEFAULT 0,
                note        TEXT,
                enabled     INTEGER NOT NULL DEFAULT 1,
                last_run    INTEGER,
                created_at  INTEGER
            );

            CREATE TABLE IF NOT EXISTS rename_rules (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER,
                rule_type   TEXT NOT NULL,
                pattern     TEXT,
                replacement TEXT,
                ordering    INTEGER NOT NULL DEFAULT 0,
                enabled     INTEGER NOT NULL DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ts          INTEGER,
                task_id     INTEGER,
                level       TEXT,
                message     TEXT
            );

            CREATE TABLE IF NOT EXISTS transferred (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id     INTEGER,
                fs_key      TEXT,
                name        TEXT,
                ts          INTEGER,
                UNIQUE(task_id, fs_key)
            );
            """
        )
        _migrate_single_account(c)
        _ensure_column(c, "tasks", "account_id", "INTEGER")
        # 旧任务（无绑定账号）归到首个账号
        first = c.execute("SELECT id FROM accounts ORDER BY created_at LIMIT 1").fetchone()
        if first:
            c.execute(
                "UPDATE tasks SET account_id=? WHERE account_id IS NULL",
                (first["id"],),
            )


def _ensure_column(c, table: str, col: str, decl: str) -> None:
    cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
    if col not in cols:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def _migrate_single_account(c) -> None:
    """把旧版单账号表 account 迁移到 accounts。"""
    tables = {
        r["name"]
        for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "account" not in tables:
        return
    has_any = c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]
    if has_any:
        return
    old = c.execute("SELECT * FROM account WHERE id=1").fetchone()
    if old and old["username"]:
        now = int(time.time())
        c.execute(
            "INSERT INTO accounts(username, cookies, bdstoken, is_active, "
            "created_at, updated_at) VALUES (?,?,?,1,?,?)",
            (old["username"], old["cookies"], old["bdstoken"], now, now),
        )
    c.execute("DROP TABLE account")


# ---- accounts ----
def add_account(username: str, cookies: dict, bdstoken: str = "") -> int:
    """新增或更新账号（按用户名去重）。首个账号自动设为活跃。"""
    now = int(time.time())
    with get_conn() as c:
        existing = c.execute(
            "SELECT id FROM accounts WHERE username=?", (username,)
        ).fetchone()
        if existing:
            c.execute(
                "UPDATE accounts SET cookies=?, bdstoken=?, updated_at=? WHERE id=?",
                (json.dumps(cookies), bdstoken, now, existing["id"]),
            )
            acc_id = existing["id"]
        else:
            cur = c.execute(
                "INSERT INTO accounts(username, cookies, bdstoken, is_active, "
                "created_at, updated_at) VALUES (?,?,?,0,?,?)",
                (username, json.dumps(cookies), bdstoken, now, now),
            )
            acc_id = cur.lastrowid
        # 若当前没有活跃账号，把它设为活跃
        active = c.execute(
            "SELECT COUNT(*) n FROM accounts WHERE is_active=1"
        ).fetchone()["n"]
        if not active:
            c.execute("UPDATE accounts SET is_active=1 WHERE id=?", (acc_id,))
    return acc_id


def _row_to_account(row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "cookies": json.loads(row["cookies"] or "{}"),
        "bdstoken": row["bdstoken"],
        "is_active": row["is_active"],
    }


def list_accounts() -> list[dict]:
    with get_conn() as c:
        rows = c.execute("SELECT * FROM accounts ORDER BY created_at").fetchall()
    return [_row_to_account(r) for r in rows]


def get_account(account_id: int) -> Optional[dict]:
    with get_conn() as c:
        row = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    return _row_to_account(row) if row else None


def get_active_account() -> Optional[dict]:
    with get_conn() as c:
        row = c.execute(
            "SELECT * FROM accounts WHERE is_active=1 LIMIT 1"
        ).fetchone()
        if not row:
            row = c.execute("SELECT * FROM accounts ORDER BY created_at LIMIT 1").fetchone()
    return _row_to_account(row) if row else None


def set_active_account(account_id: int) -> None:
    with get_conn() as c:
        c.execute("UPDATE accounts SET is_active=0")
        c.execute("UPDATE accounts SET is_active=1 WHERE id=?", (account_id,))


def delete_account(account_id: int) -> None:
    with get_conn() as c:
        was_active = c.execute(
            "SELECT is_active FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
        c.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        if was_active and was_active["is_active"]:
            nxt = c.execute(
                "SELECT id FROM accounts ORDER BY created_at LIMIT 1"
            ).fetchone()
            if nxt:
                c.execute("UPDATE accounts SET is_active=1 WHERE id=?", (nxt["id"],))


def account_count() -> int:
    with get_conn() as c:
        return c.execute("SELECT COUNT(*) n FROM accounts").fetchone()["n"]


# ---- tasks ----
def add_task(data: dict) -> int:
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO tasks(account_id, kind, link, pwd, target_dir, interval, "
            "rename_on, note, enabled, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                data.get("account_id"),
                data.get("kind", "share"),
                data.get("link", ""),
                data.get("pwd", ""),
                data.get("target_dir", "/"),
                data.get("interval", "daily"),
                int(data.get("rename_on", 0)),
                data.get("note", ""),
                int(data.get("enabled", 1)),
                int(time.time()),
            ),
        )
        return cur.lastrowid


def list_tasks() -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT t.*, a.username AS account_name "
            "FROM tasks t LEFT JOIN accounts a ON t.account_id=a.id "
            "ORDER BY t.created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_task(task_id: int) -> Optional[dict]:
    with get_conn() as c:
        row = c.execute(
            "SELECT t.*, a.username AS account_name "
            "FROM tasks t LEFT JOIN accounts a ON t.account_id=a.id WHERE t.id=?",
            (task_id,),
        ).fetchone()
    return dict(row) if row else None


def update_task(task_id: int, data: dict) -> None:
    with get_conn() as c:
        c.execute(
            "UPDATE tasks SET account_id=?, link=?, pwd=?, target_dir=?, "
            "interval=?, rename_on=?, note=? WHERE id=?",
            (
                data.get("account_id"),
                data.get("link", ""),
                data.get("pwd", ""),
                data.get("target_dir", "/"),
                data.get("interval", "daily"),
                int(data.get("rename_on", 0)),
                data.get("note", ""),
                task_id,
            ),
        )


def delete_task(task_id: int) -> None:
    with get_conn() as c:
        c.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        c.execute("DELETE FROM rename_rules WHERE task_id=?", (task_id,))


def set_task_enabled(task_id: int, enabled: bool) -> None:
    with get_conn() as c:
        c.execute("UPDATE tasks SET enabled=? WHERE id=?", (int(enabled), task_id))


# ---- rename rules ----
def list_rules(task_id: Optional[int] = None) -> list[dict]:
    with get_conn() as c:
        if task_id is None:
            rows = c.execute(
                "SELECT * FROM rename_rules WHERE task_id IS NULL ORDER BY ordering"
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM rename_rules WHERE task_id=? ORDER BY ordering",
                (task_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def replace_rules(task_id: Optional[int], rules: Iterable[dict]) -> None:
    with get_conn() as c:
        if task_id is None:
            c.execute("DELETE FROM rename_rules WHERE task_id IS NULL")
        else:
            c.execute("DELETE FROM rename_rules WHERE task_id=?", (task_id,))
        for i, r in enumerate(rules):
            c.execute(
                "INSERT INTO rename_rules(task_id, rule_type, pattern, replacement, "
                "ordering, enabled) VALUES (?,?,?,?,?,?)",
                (
                    task_id,
                    r["rule_type"],
                    r.get("pattern", ""),
                    r.get("replacement", ""),
                    i,
                    int(r.get("enabled", 1)),
                ),
            )


# ---- logs ----
def add_log(level: str, message: str, task_id: Optional[int] = None) -> None:
    with get_conn() as c:
        c.execute(
            "INSERT INTO logs(ts, task_id, level, message) VALUES (?,?,?,?)",
            (int(time.time()), task_id, level, message),
        )


def list_logs(limit: int = 200) -> list[dict]:
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


# ---- dedup ----
def is_transferred(task_id: int, fs_key: str) -> bool:
    with get_conn() as c:
        row = c.execute(
            "SELECT 1 FROM transferred WHERE task_id=? AND fs_key=?", (task_id, fs_key)
        ).fetchone()
    return row is not None


def mark_transferred(task_id: int, fs_key: str, name: str) -> None:
    with get_conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO transferred(task_id, fs_key, name, ts) "
            "VALUES (?,?,?,?)",
            (task_id, fs_key, name, int(time.time())),
        )
