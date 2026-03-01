"""
YouTube Family Monitor — Setup Checker

Run this before your first `python main.py` to verify everything is in place.
It checks Python version, installed packages, .env config, cookies, and ffmpeg.
It also makes one small test call to Gemini to confirm your API key works.
"""

import sys
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))

REQUIRED_PACKAGES = [
    ("google.genai",          "google-genai"),
    ("dotenv",                "python-dotenv"),
    ("requests",              "requests"),
    ("youtube_transcript_api","youtube-transcript-api"),
    ("yt_dlp",                "yt-dlp"),
    ("functions_framework",   "functions-framework"),
]

REQUIRED_ENV_VARS = [
    "GEMINI_API_KEY",
    "GMAIL_ADDRESS",
    "GMAIL_APP_PASSWORD",
    "REPORT_RECIPIENT",
]

_all_ok = True

def check(label, ok, fix=None):
    global _all_ok
    mark = "✓" if ok else "✗"
    print(f"  {mark}  {label}")
    if not ok:
        _all_ok = False
        if fix:
            print(f"       → {fix}")
    return ok


def main():
    global _all_ok

    print("\n=== YouTube Family Monitor — Setup Check ===\n")

    # ── Python version ────────────────────────────────────────────────────────
    print("Python")
    v = sys.version_info
    check(
        f"Python {v.major}.{v.minor}.{v.micro}",
        v >= (3, 9),
        "Requires Python 3.9 or higher — https://www.python.org/downloads/",
    )

    # ── Packages ──────────────────────────────────────────────────────────────
    print("\nPackages")
    packages_ok = True
    for import_name, pip_name in REQUIRED_PACKAGES:
        try:
            __import__(import_name)
            check(pip_name, True)
        except ImportError:
            check(pip_name, False, "Run: pip install -r requirements.txt")
            packages_ok = False

    # ── .env and required keys ────────────────────────────────────────────────
    print("\nConfiguration")
    env_path = os.path.join(HERE, ".env")
    env_ok = os.path.exists(env_path)
    check(".env file exists", env_ok, "Copy .env.example to .env and fill in your values")

    env_vars_loaded = False
    if env_ok and packages_ok:
        try:
            from dotenv import load_dotenv
            load_dotenv(env_path)
            env_vars_loaded = True
        except Exception:
            pass

    for var in REQUIRED_ENV_VARS:
        val = os.environ.get(var, "")
        filled = bool(val) and "your_" not in val.lower() and "placeholder" not in val.lower()
        check(
            f"{var} is set",
            filled,
            f"Set {var} in your .env file",
        )

    # ── Cookies ───────────────────────────────────────────────────────────────
    print("\nYouTube Cookies")
    cookie_files = [
        f for f in os.listdir(HERE)
        if f.endswith("_cookies.json") or f == "cookies.json"
    ]
    if cookie_files:
        check(f"Cookie file found ({cookie_files[0]})", True)
    else:
        check(
            "Cookie file found",
            False,
            "Export YouTube cookies using the Cookie-Editor browser extension "
            "and save as www.youtube.com_cookies.json in this folder (see README)",
        )

    # ── ffmpeg ────────────────────────────────────────────────────────────────
    print("\nffmpeg (needed for audio analysis)")
    check(
        "ffmpeg on PATH",
        shutil.which("ffmpeg") is not None,
        "Download from https://ffmpeg.org/download.html and add to PATH",
    )

    # ── Gemini API ────────────────────────────────────────────────────────────
    print("\nGemini API (making one test call...)")
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or "your_" in api_key.lower():
        check("Gemini API key works", False, "Set GEMINI_API_KEY in your .env file first")
    elif not packages_ok:
        check("Gemini API key works", False, "Install packages first (pip install -r requirements.txt)")
    else:
        try:
            from google import genai
            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents='Reply with exactly the single word: OK',
            )
            check("Gemini API key works", True)
        except Exception as e:
            check("Gemini API key works", False, str(e))

    # ── Summary ───────────────────────────────────────────────────────────────
    print()
    if _all_ok:
        print("All checks passed — you're ready to run: python main.py")
    else:
        print("Some checks failed. Fix the issues above, then re-run this script.")
    print()


if __name__ == "__main__":
    main()
