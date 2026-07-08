import os
import sys
import glob
import subprocess
import sqlite3
import shutil
import json
import time
import asyncio
from typing import Dict, Any

sys.path.append(os.path.join(os.path.abspath(os.path.dirname(__file__)), ".."))
from bilibili_api import live, Credential

# Dynamic cookie extraction from Firefox default profile
def get_firefox_cookies() -> Dict[str, str]:
    appdata = os.environ.get('APPDATA')
    if not appdata:
        print("APPDATA environment variable not found.")
        return {}
    
    profiles_path = os.path.join(appdata, 'Mozilla', 'Firefox', 'Profiles')
    pattern = os.path.join(profiles_path, '*', 'cookies.sqlite')
    found = glob.glob(pattern)
    if not found:
        print("No Firefox cookies database found.")
        return {}
    
    cookie_path = found[0]
    temp_path = 'temp_listener_cookies.sqlite'
    shutil.copyfile(cookie_path, temp_path)
    
    conn = sqlite3.connect(temp_path)
    cursor = conn.cursor()
    
    query = "SELECT name, value FROM moz_cookies WHERE host LIKE '%bilibili.com%'"
    cursor.execute(query)
    
    cookies = {}
    for name, value in cursor.fetchall():
        if name in ['SESSDATA', 'bili_jct', 'buvid3', 'buvid4', 'DedeUserID']:
            cookies[name] = value
            
    conn.close()
    try:
        os.remove(temp_path)
    except Exception:
        pass
    return cookies

# Setup SQLite Database
def setup_db(db_path: str):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS livechat_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp REAL,
            event_type TEXT,
            raw_data TEXT
        )
    ''')
    conn.commit()
    conn.close()

def log_event_to_db(db_path: str, event_type: str, data: Any):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO livechat_events (timestamp, event_type, raw_data) VALUES (?, ?, ?)",
        (time.time(), event_type, json.dumps(data, ensure_ascii=False))
    )
    conn.commit()
    conn.close()

async def main():
    room_id = 23596840
    db_path = 'livechat_events.db'
    setup_db(db_path)
    
    # Load already seen event types from DB
    seen_event_types = set()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT event_type FROM livechat_events")
        seen_event_types = {row[0] for row in cursor.fetchall()}
        conn.close()
        print(f"Loaded {len(seen_event_types)} existing event types from database.")
    except Exception as e:
        print(f"Failed to load seen event types: {e}")
        
    print("Extracting Bilibili cookies from Firefox...")
    cookies = get_firefox_cookies()
    if not cookies:
        print("Warning: Could not extract credentials. Connecting anonymously.")
        credential = Credential()
    else:
        print("Successfully loaded credentials from Firefox.")
        credential = Credential(
            sessdata=cookies.get('SESSDATA'),
            bili_jct=cookies.get('bili_jct'),
            buvid3=cookies.get('buvid3'),
            buvid4=cookies.get('buvid4')
        )
        
    print(f"Connecting to room_id {room_id}...")
    room = live.LiveDanmaku(room_id, credential=credential)
    
    # Trigger initial wiki build at startup
    subprocess.Popen([sys.executable, os.path.join(os.path.abspath(os.path.dirname(__file__)), "build_wiki.py")])
    
    message_counter = 0
    
    @room.on("ALL")
    async def on_all(event):
        nonlocal message_counter
        event_type = event.get("type", "UNKNOWN")
        event_data = event.get("data")
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Received event: {event_type}")
        
        # Log to SQLite
        try:
            log_event_to_db(db_path, event_type, event_data)
        except Exception as e:
            print(f"DB Log Error: {e}", file=sys.stderr)
            
        # Check if this is a new event type
        is_new_type = event_type not in seen_event_types
        message_counter += 1
        
        if is_new_type or message_counter % 50 == 0:
            if is_new_type:
                seen_event_types.add(event_type)
                print(f"New event type discovered: {event_type}! Rebuilding wiki...")
            else:
                print("Periodic wiki rebuild (every 50 messages)...")
                
            try:
                subprocess.Popen([sys.executable, os.path.join(os.path.abspath(os.path.dirname(__file__)), "build_wiki.py")])
            except Exception as e:
                print(f"Failed to launch wiki compiler: {e}", file=sys.stderr)
            
    try:
        await room.connect()
    except asyncio.CancelledError:
        print("Listener canceled.")
    except Exception as e:
        print(f"Websocket error: {e}", file=sys.stderr)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Stopped by user.")
