import requests
import json
import db
import os
import time
import hashlib
import traceback

def write_netscape_cookies(cookie_data, out_path="/tmp/youtube_cookies.txt"):
    """Convert JSON cookies to Netscape format for yt-dlp to use."""
    try:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write("# Netscape HTTP Cookie File\n")
            f.write("# https://curl.haxx.se/rfc/cookie_spec.html\n")
            f.write("# This is a generated file!  Do not edit.\n\n")
            
            for c in cookie_data:
                domain = c.get('domain', '')
                include_subdomains = 'TRUE' if domain.startswith('.') else 'FALSE'
                path = c.get('path', '/')
                secure = 'TRUE' if c.get('secure', False) else 'FALSE'
                expires = str(int(c.get('expirationDate', 0)))
                name = c.get('name', '')
                value = c.get('value', '')
                
                f.write(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    except Exception as e:
        print(f"Failed to write Netscape cookies: {e}")

def get_youtube_cookies(browser_name="chrome"):
    """Extract YouTube cookies from local file or Google Secret Manager."""
    cookie_data = None

    # Cloud mode: load from Secret Manager
    if os.environ.get("GCS_BUCKET"):
        try:
            from google.cloud import secretmanager
            client = secretmanager.SecretManagerServiceClient()
            project_id = os.environ.get("GCP_PROJECT", "youtube-monitor-488819")
            secret_name = f"projects/{project_id}/secrets/youtube-cookies/versions/latest"
            response = client.access_secret_version(name=secret_name)
            cookie_data = json.loads(response.payload.data.decode("UTF-8"))
            print("Loaded cookies from Secret Manager.")
        except Exception as e:
            print(f"Failed to load cookies from Secret Manager: {e}")
            return None
    else:
        # Local mode: load from file
        cookie_file = os.path.join(os.path.dirname(__file__), "www.youtube.com_cookies.json")
        print(f"Looking for '{cookie_file}'...")
        
        if not os.path.exists(cookie_file):
            print(f"Error: Could not find {cookie_file}.")
            return None
            
        try:
            with open(cookie_file, 'r', encoding='utf-8') as f:
                cookie_data = json.load(f)
        except Exception as e:
            print(f"Failed to load cookies JSON: {e}")
            return None

    if not cookie_data:
        return None
    # Write out for yt-dlp to use
    write_netscape_cookies(cookie_data)

    session = requests.Session()
    for cookie in cookie_data:
        session.cookies.set(
            cookie.get('name', ''), 
            cookie.get('value', ''), 
            domain=cookie.get('domain', '')
        )
    return session



def get_sapisid_hash(session):
    """Generate the SAPISIDHASH required for YouTube InnerTube API authentication."""
    sapisid = None
    for cookie in session.cookies:
        if cookie.name in ['SAPISID', '__Secure-3PAPISID']:
            sapisid = cookie.value
            break
            
    if not sapisid:
        return None
        
    timestamp = str(int(time.time()))
    msg = f"{timestamp} {sapisid} https://www.youtube.com"
    hash_val = hashlib.sha1(msg.encode("utf-8")).hexdigest()
    return f"SAPISIDHASH {timestamp}_{hash_val}"

def fetch_history_page(session, api_key, client_context, continuation_token=None):
    """Fetch a single page of history using the internal YouTube API (innertube)."""
    api_url = f"https://www.youtube.com/youtubei/v1/browse?key={api_key}"
    
    payload = {
        "context": client_context
    }
    
    if continuation_token:
        payload["continuation"] = continuation_token
    else:
        payload["browseId"] = "FEhistory"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://www.youtube.com",
        "Referer": "https://www.youtube.com/feed/history",
        "Content-Type": "application/json"
    }
    
    auth_header = get_sapisid_hash(session)
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        res = session.post(api_url, headers=headers, json=payload)
        if res.status_code == 200:
            return res.json()
    except Exception as e:
        print(f"API request failed: {e}")
    return None

def fetch_all_history(session, max_videos=200):
    """Fetches YouTube history, paginating until max_videos is reached."""
    print("Fetching YouTube homepage to obtain API context...")
    
    response = session.get("https://www.youtube.com/", headers={"User-Agent": "Mozilla/5.0"})
    if response.status_code != 200:
        print(f"Failed to load YouTube: HTTP {response.status_code}")
        return []

    html = response.text
    
    # Extract Innertube API Key
    try:
        api_key = html.split('"INNERTUBE_API_KEY":"')[1].split('"')[0]
        client_name = int(html.split('"INNERTUBE_CONTEXT_CLIENT_NAME":')[1].split(',')[0])
        client_version = html.split('"INNERTUBE_CONTEXT_CLIENT_VERSION":"')[1].split('"')[0]
    except IndexError:
        print("Could not find API context. Are cookies valid and logged in?")
        return []

    client_context = {
        "client": {
            "clientName": client_name,
            "clientVersion": client_version,
            "hl": "en",
            "gl": "US"
        }
    }

    all_videos = []
    continuation_token = None
    page = 1
    
    print(f"Successfully obtained API Key. Fetching history feed...")

    while len(all_videos) < max_videos:
        print(f"Fetching page {page}...")
        data = fetch_history_page(session, api_key, client_context, continuation_token)
        if not data:
            break
            
        videos_on_page, next_token = parse_history_page(data, is_continuation=(continuation_token is not None))
        all_videos.extend(videos_on_page)
        
        if not next_token:
            break
            
        continuation_token = next_token
        page += 1
        
    return all_videos[:max_videos]

def parse_history_page(data, is_continuation=False):
    """Parses a single JSON response, returning (videos_list, next_continuation_token)."""
    videos = []
    next_token = None
    
    try:
        if not is_continuation:
            tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
            history_tab = next((t["tabRenderer"] for t in tabs if "tabRenderer" in t and t["tabRenderer"].get("selected")), None)
            if not history_tab:
                return videos, None
            sections_container = history_tab.get("content", {}).get("sectionListRenderer", {}).get("contents", [])
        else:
            # Continuation responses have a different structure
            sections_container = data.get("onResponseReceivedActions", [{}])[0].get("appendContinuationItemsAction", {}).get("continuationItems", [])
            
        for section in sections_container:
            # Check for videos
            item_section = section.get("itemSectionRenderer", {})

            # Extract the day-group label YouTube shows (e.g. "Today", "Yesterday", "Wednesday")
            header = item_section.get("header", {}).get("itemSectionHeaderRenderer", {})
            title_runs = header.get("title", {}).get("runs", [])
            section_label = title_runs[0].get("text", "") if title_runs else ""

            contents = item_section.get("contents", [])
            for item in contents:
                video_renderer = item.get("videoRenderer")
                if video_renderer:
                    video_id = video_renderer.get("videoId")
                    title = video_renderer.get("title", {}).get("runs", [{}])[0].get("text", "Unknown")
                    owner_text = video_renderer.get("ownerText", {}).get("runs", [{}])
                    channel = owner_text[0].get("text", "Unknown Channel") if owner_text else "Unknown Channel"
                    videos.append({
                        "video_id": video_id,
                        "title": title,
                        "channel": channel,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "watched_label": section_label,
                    })
            
            # Check for the next continuation token in the sectionList
            conts = section.get("continuationItemRenderer", {}).get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
            if conts:
                next_token = conts
                
        # Sometimes the continuation token sits outside the itemSectionRenderer on the root level
        if not next_token and not is_continuation:
             for s in sections_container:
                 if "continuationItemRenderer" in s:
                     next_token = s["continuationItemRenderer"].get("continuationEndpoint", {}).get("continuationCommand", {}).get("token")
                     
    except Exception as e:
        print(f"Error parsing JSON: {e}")
        traceback.print_exc()
        
    if not videos and not is_continuation:
        # It's an empty feed (often contains a 'messageRenderer' instead of 'videoRenderer')
        print("[Info] No playable videos found in this history slice.")
             
    return videos, next_token

def run_collection(browser_name="chrome", max_videos=200):
    """Orchestrates cookie extraction, API fetching, DB deduplication, and returns list of NEW videos."""
    session = get_youtube_cookies(browser_name)
    if not session:
        return {"error": "cookie_failure", "videos": []}
        
    parsed_videos = fetch_all_history(session, max_videos)
    if not parsed_videos:
        print("Warning: API returned no videos or failed to fetch.")
        return {"error": "api_failure", "videos": []}
        
    print(f"Found {len(parsed_videos)} videos in history backlog.")
    
    from datetime import datetime
    new_videos = []
    for v in parsed_videos:
        if not db.video_exists(v["video_id"]):
            now = datetime.now().isoformat()
            watched_at = v.get("watched_label") or now
            db.insert_video(v["video_id"], v["title"], v["channel"], v["url"], watched_at=watched_at)
            v["recorded_at"] = now
            new_videos.append(v)
            
    print(f"Identified {len(new_videos)} completely new videos to analyze.")
    return {"error": None, "videos": new_videos}

if __name__ == "__main__":
    db.init_db()
    result = run_collection("chrome", 50)
    print(json.dumps(result, indent=2))
