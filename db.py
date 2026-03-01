import sqlite3
import os
from datetime import datetime

# In Cloud Functions, we must use /tmp/ for writable storage
IS_CLOUD = os.environ.get("GCS_BUCKET") is not None
GCS_BUCKET = os.environ.get("GCS_BUCKET", "")
GCS_DB_BLOB = "youtube_audit/processed_videos.db"

if IS_CLOUD:
    DB_PATH = "/tmp/processed_videos.db"
else:
    DB_PATH = os.path.join(os.path.dirname(__file__), "processed_videos.db")

def download_db_from_cloud():
    """Download the SQLite DB from Google Cloud Storage (if it exists)."""
    if not IS_CLOUD:
        return
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(GCS_DB_BLOB)
        if blob.exists():
            blob.download_to_filename(DB_PATH)
            print(f"Downloaded DB from gs://{GCS_BUCKET}/{GCS_DB_BLOB}")
        else:
            print("No existing DB in cloud storage. Starting fresh.")
    except Exception as e:
        print(f"Failed to download DB from cloud: {e}")

def upload_db_to_cloud():
    """Upload the SQLite DB back to Google Cloud Storage."""
    if not IS_CLOUD:
        return
    try:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(GCS_DB_BLOB)
        blob.upload_from_filename(DB_PATH)
        print(f"Uploaded DB to gs://{GCS_BUCKET}/{GCS_DB_BLOB}")
    except Exception as e:
        print(f"Failed to upload DB to cloud: {e}")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            title TEXT,
            channel TEXT,
            watched_at TEXT,
            recorded_at TEXT,
            url TEXT,
            transcript_status TEXT,
            transcript_text TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analysis (
            video_id TEXT PRIMARY KEY,
            risk_level TEXT,
            categories TEXT,
            summary TEXT,
            confidence REAL,
            rationale TEXT,
            analyzed_at TEXT,
            FOREIGN KEY(video_id) REFERENCES videos(video_id)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT,
            ended_at TEXT,
            status TEXT,
            videos_found INTEGER,
            error TEXT
        )
    ''')

    conn.commit()
    conn.close()

def video_exists(video_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM videos WHERE video_id = ?", (video_id,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def insert_video(video_id, title, channel, url, watched_at=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        INSERT OR IGNORE INTO videos (video_id, title, channel, watched_at, recorded_at, url)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (video_id, title, channel, watched_at or now, now, url))
    conn.commit()
    conn.close()

def update_transcript(video_id, status, text=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE videos 
        SET transcript_status = ?, transcript_text = ? 
        WHERE video_id = ?
    ''', (status, text, video_id))
    conn.commit()
    conn.close()

def insert_analysis(video_id, risk_level, categories, summary, confidence, rationale):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        INSERT OR REPLACE INTO analysis 
        (video_id, risk_level, categories, summary, confidence, rationale, analyzed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (video_id, risk_level, categories, summary, confidence, rationale, now))
    conn.commit()
    conn.close()

def get_unanalyzed_videos():
    """Returns a list of videos that don't have an entry in the analysis table."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT v.video_id, v.title, v.channel, v.url, v.recorded_at, v.watched_at
        FROM videos v
        LEFT JOIN analysis a ON v.video_id = a.video_id
        WHERE a.video_id IS NULL
    ''')

    unanalyzed = []
    for row in cursor.fetchall():
        unanalyzed.append({
            "video_id": row[0],
            "title": row[1],
            "channel": row[2],
            "url": row[3],
            "recorded_at": row[4],
            "watched_at": row[5],
        })
    conn.close()
    return unanalyzed

def start_run():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        INSERT INTO runs (started_at, status)
        VALUES (?, 'started')
    ''', (now,))
    run_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return run_id

def finish_run(run_id, status, videos_found=0, error=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    cursor.execute('''
        UPDATE runs 
        SET ended_at = ?, status = ?, videos_found = ?, error = ?
        WHERE run_id = ?
    ''', (now, status, videos_found, error, run_id))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
