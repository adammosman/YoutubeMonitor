"""
YouTube Kids watch history collector.

Uses Playwright with a persistent browser profile so the parental gate only
needs to be completed once. Subsequent runs are fully headless.

First run (setup):
    python kids_collector.py --setup
    A browser window opens. Complete the YouTube Kids setup / parental gate,
    then press Enter in this terminal. The profile is saved for future runs.

Normal run (called by main.py):
    result = run_kids_collection(max_videos=200)
"""

import json
import os
import sys
import asyncio
import traceback
from pathlib import Path
from datetime import datetime

HERE = Path(__file__).parent
PROFILE_DIR = HERE / "ytk_browser_profile"
SETUP_SENTINEL = PROFILE_DIR / ".setup_complete"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_pw_cookies(filename):
    path = HERE / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    result = []
    for c in raw:
        domain = c.get("domain", "")
        if not domain.startswith("."):
            domain = "." + domain.lstrip(".")
        entry = {
            "name":     c.get("name", ""),
            "value":    c.get("value", ""),
            "domain":   domain,
            "path":     c.get("path", "/"),
            "secure":   c.get("secure", False),
            "httpOnly": c.get("httpOnly", False),
            "sameSite": "None",
        }
        if entry["name"] and entry["value"]:
            result.append(entry)
    return result


def is_setup_complete():
    return SETUP_SENTINEL.exists()


# ── Core async logic ──────────────────────────────────────────────────────────

async def _run_async(headless: bool, max_videos: int) -> list:
    from playwright.async_api import async_playwright

    PROFILE_DIR.mkdir(exist_ok=True)
    kids_cookies = _load_pw_cookies("www.youtubekids.com_cookies.json")

    if not kids_cookies:
        print("[kids_collector] No YouTube Kids cookies found (www.youtubekids.com_cookies.json).")
        return []

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            args=["--no-sandbox"],
        )

        # Refresh the known kids cookies into the profile on every run
        # (handles cookie expiry)
        try:
            await context.add_cookies(kids_cookies)
        except Exception as e:
            print(f"[kids_collector] Warning: could not add cookies: {e}")

        page = await context.new_page()

        print("[kids_collector] Navigating to YouTube Kids watch history...")
        try:
            await page.goto(
                "https://www.youtubekids.com/watchitagain",
                wait_until="load",
                timeout=30_000,
            )
        except Exception as e:
            print(f"[kids_collector] Navigation error: {e}")
            await context.close()
            return []

        if not headless:
            # ── SETUP MODE ────────────────────────────────────────────────────
            print()
            print("=" * 65)
            print("YOUTUBE KIDS SETUP")
            print("=" * 65)
            print(
                "A browser window should be open. If you see a parental gate\n"
                "or 'Set up YouTube Kids', complete it now.\n"
                "\n"
                "Once the Watch Again page shows your child's videos,\n"
                "come back here and press Enter to save the session."
            )
            print("=" * 65)
            # Use executor so async doesn't block
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, input, "\n>>> Press Enter when ready: ")

            # Verify the gate is gone
            gate = await page.query_selector("ytk-parental-gate")
            if gate:
                print("[kids_collector] WARNING: Parental gate still visible. Setup may be incomplete.")
                print("                Re-run --setup and complete the gate before pressing Enter.")
            else:
                SETUP_SENTINEL.write_text(datetime.now().isoformat())
                print("[kids_collector] Setup complete. Profile saved.")
        else:
            # ── HEADLESS MODE ─────────────────────────────────────────────────
            await page.wait_for_timeout(5_000)

            gate = await page.query_selector("ytk-parental-gate")
            if gate:
                print(
                    "[kids_collector] Parental gate detected — run setup first:\n"
                    "                 python kids_collector.py --setup"
                )
                await context.close()
                return []

        # ── Fetch watch history via InnerTube from within the page ────────────
        # Calling fetch() from page.evaluate() uses the browser's own auth
        # context (cookies, XSRF tokens, OAuth state) — no manual auth needed.
        print("[kids_collector] Fetching watch history via InnerTube API...")

        all_videos: list = []
        continuation_token = None
        page_num = 1

        while len(all_videos) < max_videos:
            if page_num > 1:
                print(f"[kids_collector] Fetching page {page_num} (continuation)...")

            payload: dict
            if continuation_token:
                payload = {"continuation": continuation_token}
            else:
                payload = {"browseId": "FEhistory"}

            raw = await page.evaluate(
                """
                async ([payload]) => {
                    try {
                        const apiKey = ytcfg.get('INNERTUBE_API_KEY');
                        const ctx = {
                            client: {
                                clientName:    ytcfg.get('INNERTUBE_CONTEXT_CLIENT_NAME'),
                                clientVersion: ytcfg.get('INNERTUBE_CONTEXT_CLIENT_VERSION'),
                                hl: 'en',
                                gl: 'US',
                            }
                        };
                        const body = Object.assign({context: ctx}, payload);
                        const resp = await fetch(
                            '/youtubei/v1/browse?key=' + apiKey,
                            {
                                method: 'POST',
                                headers: {'Content-Type': 'application/json'},
                                credentials: 'include',
                                body: JSON.stringify(body),
                            }
                        );
                        const status = resp.status;
                        const data = await resp.json();
                        return {status, data};
                    } catch(e) {
                        return {status: 0, error: e.toString()};
                    }
                }
                """,
                [payload],
            )

            if raw.get("error"):
                print(f"[kids_collector] JS error: {raw['error']}")
                break

            status = raw.get("status", 0)
            if status != 200:
                print(f"[kids_collector] InnerTube returned HTTP {status} on page {page_num}")
                if status == 401:
                    print(
                        "[kids_collector] 401 Unauthorized — if this persists after setup,\n"
                        "                 try re-exporting www.youtubekids.com_cookies.json\n"
                        "                 and running setup again."
                    )
                break

            data = raw.get("data", {})
            videos_on_page, continuation_token = _parse_history(data, is_continuation=(page_num > 1))
            all_videos.extend(videos_on_page)

            if not continuation_token:
                break

            page_num += 1

        await context.close()

    print(f"[kids_collector] Retrieved {len(all_videos)} videos from watch history.")
    return all_videos[:max_videos]


def _parse_history(data: dict, is_continuation: bool) -> tuple:
    """
    Parse a single InnerTube browse response.
    Returns (videos_list, next_continuation_token_or_None).
    """
    videos = []
    next_token = None

    try:
        if not is_continuation:
            tabs = (
                data.get("contents", {})
                    .get("twoColumnBrowseResultsRenderer", {})
                    .get("tabs", [])
            )
            history_tab = next(
                (t["tabRenderer"] for t in tabs
                 if "tabRenderer" in t and t["tabRenderer"].get("selected")),
                None,
            )
            if not history_tab:
                return videos, None
            sections = (
                history_tab.get("content", {})
                            .get("sectionListRenderer", {})
                            .get("contents", [])
            )
        else:
            sections = (
                data.get("onResponseReceivedActions", [{}])[0]
                    .get("appendContinuationItemsAction", {})
                    .get("continuationItems", [])
            )

        for section in sections:
            item_section = section.get("itemSectionRenderer", {})

            header = item_section.get("header", {}).get("itemSectionHeaderRenderer", {})
            title_runs = header.get("title", {}).get("runs", [])
            section_label = title_runs[0].get("text", "") if title_runs else ""

            for item in item_section.get("contents", []):
                vr = item.get("videoRenderer")
                if vr:
                    video_id = vr.get("videoId")
                    title = (
                        vr.get("title", {}).get("runs", [{}])[0].get("text", "Unknown")
                    )
                    owner = vr.get("ownerText", {}).get("runs", [{}])
                    channel = owner[0].get("text", "Unknown Channel") if owner else "Unknown Channel"
                    if video_id:
                        videos.append({
                            "video_id":     video_id,
                            "title":        title,
                            "channel":      channel,
                            "url":          f"https://www.youtube.com/watch?v={video_id}",
                            "watched_label": section_label,
                            "source":       "youtube_kids",
                        })

            cont = (
                section.get("continuationItemRenderer", {})
                       .get("continuationEndpoint", {})
                       .get("continuationCommand", {})
                       .get("token")
            )
            if cont:
                next_token = cont

        if not next_token and not is_continuation:
            for s in sections:
                if "continuationItemRenderer" in s:
                    next_token = (
                        s["continuationItemRenderer"]
                        .get("continuationEndpoint", {})
                        .get("continuationCommand", {})
                        .get("token")
                    )

    except Exception:
        traceback.print_exc()

    return videos, next_token


# ── Public API ────────────────────────────────────────────────────────────────

def run_kids_collection(max_videos: int = 200) -> dict:
    """
    Collect new YouTube Kids videos. Returns same shape as collector.run_collection().
    """
    import db

    if not is_setup_complete():
        print(
            "[kids_collector] YouTube Kids browser profile not set up.\n"
            "                 Run:  python kids_collector.py --setup"
        )
        return {"error": "kids_not_setup", "videos": []}

    try:
        videos = asyncio.run(_run_async(headless=True, max_videos=max_videos))
    except Exception as e:
        print(f"[kids_collector] Collection failed: {e}")
        traceback.print_exc()
        return {"error": "kids_collection_failed", "videos": []}

    if not videos:
        return {"error": None, "videos": []}

    new_videos = []
    now = datetime.now().isoformat()
    for v in videos:
        if not db.video_exists(v["video_id"]):
            watched_at = v.get("watched_label") or now
            db.insert_video(
                v["video_id"], v["title"], v["channel"], v["url"],
                watched_at=watched_at,
            )
            v["recorded_at"] = now
            new_videos.append(v)

    print(f"[kids_collector] {len(new_videos)} new YouTube Kids videos to analyze.")
    return {"error": None, "videos": new_videos}


def run_setup():
    """Interactive first-time setup. Opens a headed browser for parental gate completion."""
    print("\n[kids_collector] Starting YouTube Kids setup...")
    asyncio.run(_run_async(headless=False, max_videos=0))


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--setup" in sys.argv:
        run_setup()
    else:
        import db
        db.init_db()
        result = run_kids_collection(max_videos=50)
        print(json.dumps({"error": result["error"], "count": len(result["videos"])}, indent=2))
        for v in result["videos"][:5]:
            print(f"  {v['title'][:60]}  ({v['channel']})")
