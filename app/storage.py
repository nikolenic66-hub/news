import aiosqlite
from .config import DB_PATH,MAX_HISTORY

async def init_db():
 async with aiosqlite.connect(DB_PATH) as db:
  await db.executescript("""
  CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,user_id INTEGER,username TEXT,display_name TEXT,role TEXT NOT NULL,content TEXT NOT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
  CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id,id);
  CREATE TABLE IF NOT EXISTS group_memory(chat_id INTEGER PRIMARY KEY,memory TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS settings(chat_id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1,activity REAL DEFAULT NULL,persona TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS users(chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,display_name TEXT,username TEXT,last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(chat_id,user_id));
  """)
  # Add settings.activity column to legacy DBs if the old schema lacks it.
  columns=await (await db.execute("PRAGMA table_info(settings)")).fetchall()
  if columns and not any(row[1]=="activity" for row in columns):
   await db.execute("ALTER TABLE settings ADD COLUMN activity REAL DEFAULT NULL")
  await db.commit()

async def add_message(chat_id,user_id,username,display_name,role,content):
 async with aiosqlite.connect(DB_PATH) as db:
  await db.execute("INSERT INTO messages(chat_id,user_id,username,display_name,role,content) VALUES(?,?,?,?,?,?)",(chat_id,user_id,username,display_name,role,(content or "")[:4000]))
  await db.execute("DELETE FROM messages WHERE chat_id=? AND id NOT IN (SELECT id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?)",(chat_id,chat_id,MAX_HISTORY*3))
  if user_id is not None:
   await db.execute("""INSERT INTO users(chat_id,user_id,display_name,username) VALUES(?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET display_name=excluded.display_name,username=excluded.username,last_seen=CURRENT_TIMESTAMP""",(chat_id,user_id,display_name,username))
  await db.commit()

async def history(chat_id,limit=MAX_HISTORY):
 async with aiosqlite.connect(DB_PATH) as db:
  cur=await db.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",(chat_id,limit));rows=await cur.fetchall()
 return [{"role":row[0],"content":row[1]} for row in reversed(rows)]

async def get_memory(chat_id):
 async with aiosqlite.connect(DB_PATH) as db:
  cur=await db.execute("SELECT memory FROM group_memory WHERE chat_id=?",(chat_id,));row=await cur.fetchone()
 return row[0] if row else ""

async def save_memory(chat_id,memory):
 async with aiosqlite.connect(DB_PATH) as db:
  await db.execute("INSERT INTO group_memory(chat_id,memory) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET memory=excluded.memory",(chat_id,(memory or "")[:3000]));await db.commit()

async def get_settings(chat_id):
 async with aiosqlite.connect(DB_PATH) as db:
  cur=await db.execute("SELECT enabled,activity,persona FROM settings WHERE chat_id=?",(chat_id,));row=await cur.fetchone()
 return {"enabled":bool(row[0]),"activity":row[1],"persona":row[2]} if row else {"enabled":True,"activity":None,"persona":""}

async def set_setting(chat_id,key,value):
 if key not in {"enabled","activity","persona"}:raise ValueError("Unsupported setting")
 async with aiosqlite.connect(DB_PATH) as db:
  await db.execute("INSERT OR IGNORE INTO settings(chat_id) VALUES(?)",(chat_id,))
  if key=="enabled":await db.execute("UPDATE settings SET enabled=? WHERE chat_id=?",(int(bool(value)),chat_id))
  elif key=="activity":await db.execute("UPDATE settings SET activity=? WHERE chat_id=?",(max(0,min(.5,float(value))),chat_id))
  else:await db.execute("UPDATE settings SET persona=? WHERE chat_id=?",(str(value)[:500],chat_id))
  await db.commit()

async def user_count(chat_id):
 async with aiosqlite.connect(DB_PATH) as db:
  cur=await db.execute("SELECT COUNT(*) FROM users WHERE chat_id=?",(chat_id,));return (await cur.fetchone())[0]

async def clear_chat(chat_id):
 async with aiosqlite.connect(DB_PATH) as db:
  for table in ("messages","users","group_memory"):
   await db.execute(f"DELETE FROM {table} WHERE chat_id=?",(chat_id,))
  await db.commit()
