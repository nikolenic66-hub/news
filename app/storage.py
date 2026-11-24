import aiosqlite
from .config import DB_PATH,MAX_HISTORY

async def init_db():
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  await db.execute("PRAGMA busy_timeout=30000")
  if DB_PATH != ":memory:":
   await db.execute("PRAGMA journal_mode=WAL")
  await db.executescript("""
  CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT,chat_id INTEGER NOT NULL,user_id INTEGER,username TEXT,display_name TEXT,role TEXT NOT NULL,content TEXT NOT NULL,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
  CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id,id);
  CREATE TABLE IF NOT EXISTS group_memory(chat_id INTEGER PRIMARY KEY,memory TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS settings(chat_id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL DEFAULT 1,activity REAL DEFAULT NULL,persona TEXT NOT NULL DEFAULT '');
  CREATE TABLE IF NOT EXISTS users(chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,display_name TEXT,username TEXT,last_seen DATETIME DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(chat_id,user_id));
  CREATE TABLE IF NOT EXISTS intel_items(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT NOT NULL,item_key TEXT NOT NULL UNIQUE,title TEXT NOT NULL,summary TEXT NOT NULL DEFAULT '',url TEXT NOT NULL,source TEXT NOT NULL,published_at TEXT NOT NULL DEFAULT '',fetched_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE INDEX IF NOT EXISTS idx_intel_fetched_at ON intel_items(fetched_at);
  CREATE TABLE IF NOT EXISTS promo_codes(code TEXT PRIMARY KEY,reward TEXT NOT NULL DEFAULT '',source TEXT NOT NULL,source_url TEXT NOT NULL,first_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,last_seen DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS user_activity(chat_id INTEGER NOT NULL,user_id INTEGER NOT NULL,message_count INTEGER NOT NULL DEFAULT 0,last_seen DATETIME,display_name TEXT,username TEXT,PRIMARY KEY(chat_id,user_id));
  CREATE TABLE IF NOT EXISTS app_migrations(version INTEGER PRIMARY KEY);
  """)
  columns=await (await db.execute("PRAGMA table_info(settings)")).fetchall()
  if columns and not any(row[1]=="activity" for row in columns):await db.execute("ALTER TABLE settings ADD COLUMN activity REAL DEFAULT NULL")
  # Backfill the activity counter once from messages retained by the old history table.
  migrated=await (await db.execute("SELECT 1 FROM app_migrations WHERE version=1")).fetchone()
  if not migrated:
   await db.execute("""INSERT OR IGNORE INTO user_activity(chat_id,user_id,message_count,last_seen,display_name,username)
   SELECT chat_id,user_id,COUNT(*),MAX(created_at),MAX(display_name),MAX(username)
   FROM messages WHERE role='user' AND user_id IS NOT NULL GROUP BY chat_id,user_id""")
   await db.execute("INSERT INTO app_migrations(version) VALUES(1)")
  await db.execute("DROP TABLE IF EXISTS tournament_entries")
  await db.execute("DROP TABLE IF EXISTS tournaments")
  await db.execute("DROP TABLE IF EXISTS tournament_missed")
  await db.commit()
async def add_message(chat_id,user_id,username,display_name,role,content):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  await db.execute("PRAGMA busy_timeout=30000")
  await db.execute("INSERT INTO messages(chat_id,user_id,username,display_name,role,content) VALUES(?,?,?,?,?,?)",(chat_id,user_id,username,display_name,role,(content or "")[:4000]))
  await db.execute("DELETE FROM messages WHERE chat_id=? AND id NOT IN (SELECT id FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?)",(chat_id,chat_id,MAX_HISTORY*3))
  if user_id is not None:
   await db.execute("""INSERT INTO users(chat_id,user_id,display_name,username) VALUES(?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET display_name=excluded.display_name,username=excluded.username,last_seen=CURRENT_TIMESTAMP""",(chat_id,user_id,display_name,username))
   if role == "user":
    await db.execute("""INSERT INTO user_activity(chat_id,user_id,message_count,last_seen,display_name,username)
    VALUES(?,?,1,CURRENT_TIMESTAMP,?,?)
    ON CONFLICT(chat_id,user_id) DO UPDATE SET message_count=user_activity.message_count+1,last_seen=CURRENT_TIMESTAMP,display_name=excluded.display_name,username=excluded.username""",(chat_id,user_id,display_name,username))
  await db.commit()
async def history(chat_id,limit=MAX_HISTORY):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT role,content FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",(chat_id,limit));rows=await cur.fetchall()
 return [{"role":row[0],"content":row[1]} for row in reversed(rows)]
async def get_memory(chat_id):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT memory FROM group_memory WHERE chat_id=?",(chat_id,));row=await cur.fetchone()
 return row[0] if row else ""
async def save_memory(chat_id,memory):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  await db.execute("INSERT INTO group_memory(chat_id,memory) VALUES(?,?) ON CONFLICT(chat_id) DO UPDATE SET memory=excluded.memory",(chat_id,(memory or "")[:3000]));await db.commit()
async def get_settings(chat_id):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT enabled,activity,persona FROM settings WHERE chat_id=?",(chat_id,));row=await cur.fetchone()
 return {"enabled":bool(row[0]),"activity":row[1],"persona":row[2]} if row else {"enabled":True,"activity":None,"persona":""}
async def set_setting(chat_id,key,value):
 if key not in {"enabled","activity","persona"}:raise ValueError("Unsupported setting")
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  await db.execute("INSERT OR IGNORE INTO settings(chat_id) VALUES(?)",(chat_id,))
  if key=="enabled":await db.execute("UPDATE settings SET enabled=? WHERE chat_id=?",(int(bool(value)),chat_id))
  elif key=="activity":await db.execute("UPDATE settings SET activity=? WHERE chat_id=?",(max(0,min(.5,float(value))),chat_id))
  else:await db.execute("UPDATE settings SET persona=? WHERE chat_id=?",(str(value)[:500],chat_id))
  await db.commit()
async def user_count(chat_id):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT COUNT(*) FROM users WHERE chat_id=?",(chat_id,));return (await cur.fetchone())[0]
async def clear_chat(chat_id):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  for table in ("messages","users","group_memory","user_activity"):
   await db.execute(f"DELETE FROM {table} WHERE chat_id=?",(chat_id,))
  await db.commit()
async def save_intel_item(kind,item_key,title,summary,url,source,published_at=''):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  await db.execute('PRAGMA busy_timeout=30000')
  cur=await db.execute('INSERT OR IGNORE INTO intel_items(kind,item_key,title,summary,url,source,published_at) VALUES(?,?,?,?,?,?,?)',(kind,item_key,title[:500],(summary or '')[:3000],url,source,published_at or ''))
  await db.commit()
  return cur.rowcount == 1

async def save_promo_code(code,source,source_url,reward=''):
 code=(code or '').strip().upper()
 if not code:return False
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  await db.execute('PRAGMA busy_timeout=30000')
  cur=await db.execute('INSERT OR IGNORE INTO promo_codes(code,reward,source,source_url) VALUES(?,?,?,?)',(code,(reward or '')[:300],source[:100],source_url[:1000]))
  inserted=cur.rowcount == 1
  if not inserted:
   await db.execute('UPDATE promo_codes SET last_seen=CURRENT_TIMESTAMP WHERE code=?',(code,))
  await db.commit()
  return inserted

async def get_recent_intel(limit=8):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT kind,title,summary,url,source,published_at,fetched_at FROM intel_items WHERE fetched_at >= datetime('now','-30 days') ORDER BY fetched_at DESC LIMIT ?",(max(1,min(20,int(limit))),))
  return await cur.fetchall()

async def get_recent_promo_codes(limit=8):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT code,reward,source,source_url,first_seen FROM promo_codes WHERE first_seen >= datetime('now','-30 days') ORDER BY first_seen DESC LIMIT ?",(max(1,min(20,int(limit))),))
  return await cur.fetchall()

async def get_enabled_group_chats():
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute('SELECT DISTINCT m.chat_id FROM messages m LEFT JOIN settings s ON s.chat_id=m.chat_id WHERE m.chat_id < 0 AND COALESCE(s.enabled,1)=1')
  return [row[0] for row in await cur.fetchall()]


async def get_user_stats(chat_id, user_id):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT message_count,last_seen FROM user_activity WHERE chat_id=? AND user_id=?",(chat_id,user_id))
  row=await cur.fetchone()
  return {"messages":row[0] if row else 0,"last_seen":row[1] if row else None}

async def get_top_users(chat_id, limit=10):
 async with aiosqlite.connect(DB_PATH, timeout=30) as db:
  cur=await db.execute("SELECT user_id,display_name,username,message_count FROM user_activity WHERE chat_id=? ORDER BY message_count DESC,last_seen DESC LIMIT ?",(chat_id,max(1,min(20,int(limit)))))
  return await cur.fetchall()
