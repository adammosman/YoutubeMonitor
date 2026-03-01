from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
import db

def fetch_transcript(video_id):
    """Attempt to download the transcript for a given video."""
    print(f"Fetching transcript for {video_id}...")
    try:
        api = YouTubeTranscriptApi()
        fetched = api.fetch(video_id)

        formatter = TextFormatter()
        text_transcript = formatter.format_transcript(fetched)

        # Save to database
        db.update_transcript(video_id, status="success", text=text_transcript)
        return {"status": "success", "text": text_transcript}

    except Exception as e:
        error_type = type(e).__name__
        error_msg = str(e)

        if error_type == "TranscriptsDisabled" or "Subtitles are disabled" in error_msg:
            status = "disabled"
        elif error_type == "NoTranscriptFound" or "No transcripts were found" in error_msg:
            status = "unavailable"
        elif error_type == "VideoUnavailable" or "Video is unavailable" in error_msg or "removed" in error_msg.lower():
            status = "removed"
        elif error_type in ("IpBlocked", "RequestBlocked", "PoTokenRequired"):
            status = "blocked"
        else:
            status = "error"

        print(f"Transcript failed for {video_id}: {status} ({error_type})")
        db.update_transcript(video_id, status=status, text="")
        return {"status": status, "text": ""}

import yt_dlp
import os
import sys

# MONKEYPATCH yt-dlp to stop it from crashing Google Cloud Functions by writing bytes to stderr
import yt_dlp.utils
def safe_write_string(s, out=None, encoding=None):
    if out is None:
        out = sys.stderr
    if isinstance(s, bytes):
         s = s.decode('utf-8', 'ignore')
    try:
        out.write(s)
        out.flush()
    except Exception:
        pass

yt_dlp.utils.write_string = safe_write_string

class MyLogger:
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        if isinstance(msg, bytes):
            msg = msg.decode('utf-8', 'ignore')
        print(f"yt-dlp error: {msg}")

def download_audio(video_url, video_id):
    """Downloads the audio track using yt-dlp. Returns the local filepath or None."""
    if os.environ.get("GCS_BUCKET"):
        output_dir = "/tmp/temp_audio"
    else:
        output_dir = os.path.join(os.path.dirname(__file__), "temp_audio")
        
    os.makedirs(output_dir, exist_ok=True)
    
    output_template = os.path.join(output_dir, f"{video_id}.%(ext)s")
    
    ydl_opts = {
        'format': 'm4a/bestaudio/best',
        'outtmpl': output_template,
        'quiet': True,
        'no_warnings': True,
        'logger': MyLogger()
    }
    
    if os.environ.get("GCS_BUCKET"):
        if os.path.exists("/tmp/youtube_cookies.txt"):
            ydl_opts['cookiefile'] = '/tmp/youtube_cookies.txt'
            print("Using Netscape cookies for yt-dlp authentication.")
    
    try:
        print(f"Downloading audio fallback for {video_id}...")
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract info to get the actual final filename
            info = ydl.extract_info(video_url, download=True)
            file_path = ydl.prepare_filename(info)
            
        if os.path.exists(file_path):
            return file_path
    except Exception as e:
        import traceback
        print(f"Failed to download audio for {video_id}: {e}")
        traceback.print_exc()

    return None

def enrich_videos(videos):
    """Take a list of video dicts and attach transcripts (or audio paths) to them."""
    enriched = []
    for video in videos:
        result = fetch_transcript(video["video_id"])
        
        video_copy = video.copy()
        video_copy["transcript_status"] = result["status"]
        video_copy["transcript_text"] = result["text"]
        
        if result["status"] != "success":
            # Fallback to downloading audio
            audio_path = download_audio(video["url"], video["video_id"])
            video_copy["audio_path"] = audio_path
        else:
            video_copy["audio_path"] = None
            
        enriched.append(video_copy)
        
    return enriched

