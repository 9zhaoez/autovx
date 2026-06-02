# -*- coding: utf-8 -*-
"""
记忆存储模块 — SQLite 持久化

特性:
  - SQLite 原子写入，崩溃不丢数据
  - 自动从旧 JSON 格式迁移到 SQLite
  - 自动清理 7 天前的旧记录
  - 从消息中提取关键事实（名字、年龄、地点、喜好）
"""

import os
import re
import time
import sqlite3
import logging
import json
from typing import Optional

logger = logging.getLogger("MemoryStore")

MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_memory.json")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chat_memory.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time REAL NOT NULL,
    incoming TEXT NOT NULL,
    reply TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time REAL NOT NULL,
    fact TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_conversations_time ON conversations(time DESC);
CREATE INDEX IF NOT EXISTS idx_facts_time ON facts(time DESC);
"""


class MemoryStore:
    """SQLite 对话记忆"""

    def __init__(self, max_conversations: int = 100, max_facts: int = 20):
        self.max_conversations = max_conversations
        self.max_facts = max_facts
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")  # 原子写入
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA_SQL)
        self._migrate_from_json()

    # ── 数据迁移 ──────────────────────────────────────

    def _migrate_from_json(self):
        """从旧 JSON 文件迁移数据到 SQLite"""
        if not os.path.exists(MEMORY_FILE):
            return
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
        except Exception:
            return

        if not old_data:
            return

        count = 0
        for entry in old_data:
            try:
                t = entry.get("time", 0)
                if entry.get("type") == "fact":
                    self._conn.execute(
                        "INSERT OR IGNORE INTO facts (time, fact) VALUES (?, ?)",
                        (t, entry.get("fact", ""))
                    )
                elif "incoming" in entry and "reply" in entry:
                    self._conn.execute(
                        "INSERT INTO conversations (time, incoming, reply) VALUES (?, ?, ?)",
                        (t, entry.get("incoming", ""), entry.get("reply", ""))
                    )
                count += 1
            except Exception:
                pass

        self._conn.commit()
        self._cleanup_old()

        # 迁移完成后删除旧文件
        try:
            os.rename(MEMORY_FILE, MEMORY_FILE + ".backup")
            logger.info(f"已从 JSON 迁移 {count} 条记录到 SQLite，旧文件备份为 .json.backup")
        except Exception:
            logger.info(f"已从 JSON 迁移 {count} 条记录到 SQLite")

    # ── CRUD ──────────────────────────────────────────

    def add(self, incoming_msg: str, reply_msg: str):
        """添加一条对话记录"""
        now = time.time()
        self._conn.execute(
            "INSERT INTO conversations (time, incoming, reply) VALUES (?, ?, ?)",
            (now, incoming_msg[:200], reply_msg[:200])
        )
        self._conn.commit()
        self._extract_facts(incoming_msg)
        self._trim()

    def _extract_facts(self, msg: str):
        """从消息中提取关键事实"""
        patterns = [
            (r'(?:我叫|我是|叫我|名字[是为叫]?)\s*(\S{1,8})', "对方叫{}"),
            (r'(?:我)?(\d{1,2})\s*岁', "对方{}岁"),
            (r'(?:在|去|到|住)\s*(\S{2,10}?(?:市|区|县|路|街|学校|公司|家))', "对方在/去{}"),
            (r'(喜欢|爱|讨厌|想)\s*(\S{1,15}?)(?:[的了，。,\.]|$)', "对方{}{}"),
        ]

        for pattern, template in patterns:
            m = re.search(pattern, msg)
            if not m:
                continue
            groups = m.groups()
            if len(groups) == 1:
                val = groups[0]
                fact = template.format(val)
            else:
                label, val = groups
                if val in ("我", "你", "他", "她", "什么", "干嘛"):
                    continue
                fact = template.format(label, val)

            if fact:
                try:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO facts (time, fact) VALUES (?, ?)",
                        (time.time(), fact)
                    )
                except Exception:
                    pass

        self._conn.commit()

    def _trim(self):
        """裁剪旧记录"""
        self._conn.execute("""
            DELETE FROM conversations WHERE id NOT IN (
                SELECT id FROM conversations ORDER BY time DESC LIMIT ?
            )
        """, (self.max_conversations,))
        self._conn.execute("""
            DELETE FROM facts WHERE id NOT IN (
                SELECT id FROM facts ORDER BY time DESC LIMIT ?
            )
        """, (self.max_facts,))
        self._conn.commit()
        self._cleanup_old()

    def _cleanup_old(self):
        """删除 7 天前的记录"""
        cutoff = time.time() - 7 * 86400
        self._conn.execute("DELETE FROM conversations WHERE time < ?", (cutoff,))
        self._conn.execute("DELETE FROM facts WHERE time < ?", (cutoff,))
        self._conn.commit()

    # ── 查询 ──────────────────────────────────────────

    def get_context(self, max_recent: int = 10, max_facts: int = 5) -> str:
        """获取记忆上下文，用于嵌入 AI prompt"""
        parts = []

        # 最近的事实
        rows = self._conn.execute(
            "SELECT fact FROM facts ORDER BY time DESC LIMIT ?", (max_facts,)
        ).fetchall()
        if rows:
            parts.append("你记得这些关于对方的事：" + "；".join(r[0] for r in rows))

        # 最近的对话
        rows = self._conn.execute(
            "SELECT time, incoming, reply FROM conversations ORDER BY time DESC LIMIT ?",
            (max_recent,)
        ).fetchall()
        if rows:
            lines = []
            for t, incoming, reply in reversed(rows):
                date_str = time.strftime("%m/%d %H:%M", time.localtime(t))
                lines.append(f"[{date_str}] 对方:{incoming[:40]} → 你:{reply[:40]}")
            parts.append("最近聊天记录：\n" + "\n".join(lines))

        return "\n".join(parts) if parts else ""

    def clear(self):
        """清空所有记忆"""
        self._conn.execute("DELETE FROM conversations")
        self._conn.execute("DELETE FROM facts")
        self._conn.commit()
        logger.info("记忆已清空")

    def close(self):
        """关闭数据库连接"""
        try:
            self._conn.close()
        except Exception:
            pass
