import aiosqlite
from .config import DB_PATH, MAX_HISTORY

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''CREATE TABLE IF NOT EXISTS messages (
          chat_id INTEGER NOT NULL, user_id INTEGER, username TEXT, display_name TEXT,
          role TEXT NOT NULL, content TEXT NOT NULL, ts DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts)')
        await db.execute('''CREATE TABLE IF NOT EXISTS group_memory (
          chat_id INTEGER PRIMARY KEY, memory TEXT NOT NULL DEFAULT '', updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        await db.execute('''CREATE TABLE IF NOT EXISTS user_facts (
          chat_id INTEGER NOT NULL, user_id INTEGER NOT NULL, facts TEXT NOT NULL DEFAULT '',
          PRIMARY KEY(chat_id,user_id))''')
        await db.commit()

async def add_message(chat_id, user_id, username, display_name, role, content):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO messages(chat_id,user_id,username,display_name,role,content) VALUES(?,?,?,?,?,?)',
          (chat_id,user_id,username,display_name,role,content))
        await db.execute('''DELETE FROM messages WHERE chat_id=? AND rowid NOT IN
          (SELECT rowid FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT ?)''', (chat_id,chat_id,MAX_HISTORY*3))
        await db.commit()

async def history(chat_id, limit=MAX_HISTORY):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute('SELECT role,content FROM messages WHERE chat_id=? ORDER BY rowid DESC LIMIT ?', (chat_id,limit))
        rows=await cur.fetchall()
    return [{'role':r[0],'content':r[1]} for r in reversed(rows)]

async def get_memory(chat_id):
    async with aiosqlite.connect(DB_PATH) as db:
        cur=await db.execute('SELECT memory FROM group_memory WHERE chat_id=?',(chat_id,))
        row=await cur.fetchone()
    return row[0] if row else ''

async def save_memory(chat_id, memory):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('INSERT INTO group_memory(chat_id,memory) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET memory=excluded.memory, updated_at=CURRENT_TIMESTAMP',(chat_id,memory[:4000]))
        await db.commit()
