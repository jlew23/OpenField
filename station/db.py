"""SQLite storage for the Station. Stdlib only, one file next to the run folders."""
import json, sqlite3, threading, time
from pathlib import Path

_lock = threading.RLock()
_path: Path | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  persona_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role TEXT NOT NULL,            -- user | assistant | action
  content TEXT NOT NULL,
  meta TEXT NOT NULL DEFAULT '{}',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, id);
CREATE TABLE IF NOT EXISTS songs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  bpm REAL NOT NULL DEFAULT 90,
  beats_per_bar INTEGER NOT NULL DEFAULT 4,
  song_key TEXT NOT NULL DEFAULT '',
  lyrics TEXT NOT NULL DEFAULT '',
  beat_file TEXT NOT NULL DEFAULT '',
  beat_analysis TEXT NOT NULL DEFAULT '{}',
  notes TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS remixes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  song_id INTEGER NOT NULL REFERENCES songs(id) ON DELETE CASCADE,
  persona_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  bpm REAL NOT NULL,
  feel TEXT NOT NULL DEFAULT 'normal',
  beat_file TEXT NOT NULL DEFAULT '',
  beat_analysis TEXT NOT NULL DEFAULT '{}',
  lyrics TEXT NOT NULL DEFAULT '',
  direction TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'draft',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS personas_custom (
  id TEXT PRIMARY KEY,
  data TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  room TEXT NOT NULL,
  kind TEXT NOT NULL,
  message TEXT NOT NULL,
  data TEXT NOT NULL DEFAULT '{}'
);
"""


def init(path):
    """Open (and create) the database at `path`."""
    global _path
    _path = Path(path)
    _path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as con:
        con.executescript(SCHEMA)


def connect():
    if _path is None:
        raise RuntimeError('Station database is not initialised')
    con = sqlite3.connect(_path, timeout=30, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    con.execute('PRAGMA journal_mode = WAL')
    return _Conn(con)


class _Conn:
    """Context manager that commits on success and always closes."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        _lock.acquire()
        return self.con

    def __exit__(self, exc_type, *_):
        try:
            if exc_type is None:
                self.con.commit()
            else:
                self.con.rollback()
        finally:
            self.con.close()
            _lock.release()


def row(r):
    if r is None:
        return None
    out = dict(r)
    for key in ('meta', 'beat_analysis', 'data'):
        if key in out and isinstance(out[key], str):
            try:
                out[key] = json.loads(out[key])
            except ValueError:
                out[key] = {}
    return out


def rows(rs):
    return [row(r) for r in rs]


def now():
    return time.time()


# ---------- settings ----------

def get_setting(key, default=None):
    with connect() as con:
        r = con.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if r is None:
        return default
    try:
        return json.loads(r['value'])
    except ValueError:
        return default


def set_setting(key, value):
    with connect() as con:
        con.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                    (key, json.dumps(value)))


# ---------- events (War Room feed) ----------

def log_event(room, kind, message, data=None):
    with connect() as con:
        cur = con.execute('INSERT INTO events(ts,room,kind,message,data) VALUES(?,?,?,?,?)',
                          (now(), room, kind, message, json.dumps(data or {})))
        return cur.lastrowid


def events_after(after_id=0, limit=100):
    with connect() as con:
        if after_id:
            rs = con.execute('SELECT * FROM events WHERE id>? ORDER BY id ASC LIMIT ?', (after_id, limit)).fetchall()
        else:
            rs = con.execute('SELECT * FROM (SELECT * FROM events ORDER BY id DESC LIMIT ?) ORDER BY id ASC', (limit,)).fetchall()
    return rows(rs)


# ---------- conversations ----------

def create_conversation(persona_id, title=''):
    t = now()
    with connect() as con:
        cur = con.execute('INSERT INTO conversations(persona_id,title,created_at,updated_at) VALUES(?,?,?,?)',
                          (persona_id, title, t, t))
        return cur.lastrowid


def get_conversation(cid):
    with connect() as con:
        return row(con.execute('SELECT * FROM conversations WHERE id=?', (cid,)).fetchone())


def list_conversations(persona_id=None, limit=50):
    with connect() as con:
        if persona_id:
            rs = con.execute('SELECT * FROM conversations WHERE persona_id=? ORDER BY updated_at DESC LIMIT ?',
                             (persona_id, limit)).fetchall()
        else:
            rs = con.execute('SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?', (limit,)).fetchall()
    return rows(rs)


def delete_conversation(cid):
    with connect() as con:
        con.execute('DELETE FROM conversations WHERE id=?', (cid,))


def add_message(cid, role, content, meta=None):
    t = now()
    with connect() as con:
        cur = con.execute('INSERT INTO messages(conversation_id,role,content,meta,created_at) VALUES(?,?,?,?,?)',
                          (cid, role, content, json.dumps(meta or {}), t))
        con.execute('UPDATE conversations SET updated_at=? WHERE id=?', (t, cid))
        if role == 'user':
            con.execute("UPDATE conversations SET title=? WHERE id=? AND title=''", (content[:60], cid))
        return cur.lastrowid


def get_messages(cid, limit=200):
    with connect() as con:
        rs = con.execute('SELECT * FROM (SELECT * FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?) ORDER BY id ASC',
                         (cid, limit)).fetchall()
    return rows(rs)


# ---------- songs & remixes ----------

SONG_FIELDS = ('title', 'bpm', 'beats_per_bar', 'song_key', 'lyrics', 'beat_file', 'beat_analysis', 'notes')
REMIX_FIELDS = ('persona_id', 'title', 'bpm', 'feel', 'beat_file', 'beat_analysis', 'lyrics', 'direction', 'status')


def _clean(fields, data):
    out = {}
    for k in fields:
        if k in data and data[k] is not None:
            v = data[k]
            out[k] = json.dumps(v) if k == 'beat_analysis' and not isinstance(v, str) else v
    return out


def create_song(data):
    t = now()
    vals = _clean(SONG_FIELDS, data)
    vals.setdefault('title', 'Untitled')
    cols = list(vals) + ['created_at', 'updated_at']
    with connect() as con:
        cur = con.execute(f"INSERT INTO songs({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                          [*vals.values(), t, t])
        return cur.lastrowid


def update_song(sid, data):
    vals = _clean(SONG_FIELDS, data)
    if not vals:
        return
    with connect() as con:
        con.execute(f"UPDATE songs SET {','.join(k + '=?' for k in vals)}, updated_at=? WHERE id=?",
                    [*vals.values(), now(), sid])


def get_song(sid):
    with connect() as con:
        return row(con.execute('SELECT * FROM songs WHERE id=?', (sid,)).fetchone())


def list_songs():
    with connect() as con:
        rs = con.execute('SELECT s.*, (SELECT COUNT(*) FROM remixes r WHERE r.song_id=s.id) AS remix_count '
                         'FROM songs s ORDER BY updated_at DESC').fetchall()
    return rows(rs)


def delete_song(sid):
    with connect() as con:
        con.execute('DELETE FROM songs WHERE id=?', (sid,))


def create_remix(song_id, data):
    t = now()
    vals = _clean(REMIX_FIELDS, data)
    cols = ['song_id'] + list(vals) + ['created_at', 'updated_at']
    with connect() as con:
        cur = con.execute(f"INSERT INTO remixes({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                          [song_id, *vals.values(), t, t])
        return cur.lastrowid


def update_remix(rid, data):
    vals = _clean(REMIX_FIELDS, data)
    if not vals:
        return
    with connect() as con:
        con.execute(f"UPDATE remixes SET {','.join(k + '=?' for k in vals)}, updated_at=? WHERE id=?",
                    [*vals.values(), now(), rid])


def get_remix(rid):
    with connect() as con:
        return row(con.execute('SELECT * FROM remixes WHERE id=?', (rid,)).fetchone())


def list_remixes(song_id=None):
    with connect() as con:
        if song_id:
            rs = con.execute('SELECT * FROM remixes WHERE song_id=? ORDER BY id DESC', (song_id,)).fetchall()
        else:
            rs = con.execute('SELECT * FROM remixes ORDER BY id DESC LIMIT 100').fetchall()
    return rows(rs)


def delete_remix(rid):
    with connect() as con:
        con.execute('DELETE FROM remixes WHERE id=?', (rid,))


# ---------- custom personas ----------

def list_custom_personas():
    with connect() as con:
        rs = con.execute('SELECT * FROM personas_custom').fetchall()
    out = []
    for r in rs:
        try:
            out.append(json.loads(r['data']))
        except ValueError:
            pass
    return out


def save_custom_persona(pid, data):
    with connect() as con:
        con.execute('INSERT INTO personas_custom(id,data,updated_at) VALUES(?,?,?) '
                    'ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at',
                    (pid, json.dumps(data), now()))


def delete_custom_persona(pid):
    with connect() as con:
        con.execute('DELETE FROM personas_custom WHERE id=?', (pid,))


def stats():
    with connect() as con:
        return {name: con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]
                for name in ('songs', 'remixes', 'conversations', 'messages', 'events')}
