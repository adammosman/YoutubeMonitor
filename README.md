# YouTube Family Monitor

A tool that automatically monitors a YouTube account's watch history and emails you a daily report classifying videos by risk level, with AI-powered content analysis using Google Gemini.

Built for parents who want to stay informed about what their children are watching — without manually reviewing every video.


## Features

- **Automatic history fetching** — pulls the most recent watch history via YouTube's internal API using cookies (no YouTube Data API quota needed)
- **Deep content analysis** — first tries to download captions; if unavailable, downloads and analyzes the audio track directly using Gemini
- **AI classification** — uses Google Gemini 2.5 Flash to classify each video as Low / Medium / High risk with a rationale
- **Daily email report** — HTML email with a risk summary and per-video descriptions
- **Immediate high-risk alerts** — separate email sent the moment a high-risk video is detected, before the daily report
- **Smart deduplication** — SQLite database tracks every seen video; only new videos are analyzed on each run
- **Runs locally** — no cloud required; works with Windows Task Scheduler or cron so it runs whenever your machine is on

## How It Works

```
YouTube History (via cookies)
        │
        ▼
  collector.py  ──── fetches history, deduplicates against DB
        │
        ▼
  enricher.py   ──── downloads captions (or audio as fallback)
        │
        ▼
  classifier.py ──── sends to Gemini 2.5 Flash for risk analysis
        │
        ▼
  reporter.py   ──── builds HTML report
        │
        ▼
  mailer.py     ──── sends via Gmail SMTP
```

## Prerequisites

- **Python 3.9+**
- **Google Chrome or Firefox** with the monitored YouTube account logged in
- **Gemini API key** — free tier (15 requests/min) is sufficient; get one at [aistudio.google.com](https://aistudio.google.com)
- **Gmail account** with an App Password configured (see setup step 4)
- **ffmpeg** — required by yt-dlp for audio conversion; download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to your PATH

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/youtube-monitor.git
cd youtube-monitor
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Export YouTube cookies

The tool needs cookies from a browser where the monitored YouTube account is logged in. It does **not** need your password — only the session cookies.

1. Install the **Cookie-Editor** browser extension ([Chrome](https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm) / [Firefox](https://addons.mozilla.org/en-US/firefox/addon/cookie-editor/))
2. Go to [youtube.com](https://www.youtube.com) and make sure you're logged into the account you want to monitor
3. Click the Cookie-Editor extension icon → **Export** → **Export as JSON**
4. Save the file as `www.youtube.com_cookies.json` in the project folder

> **Note:** YouTube cookies expire every few months. When the tool stops fetching history, re-export cookies and replace the file.

### 4. Set up Gmail App Password

Gmail requires an App Password (not your regular password) for SMTP access.

1. Enable 2-Step Verification on your Google account if you haven't already: [myaccount.google.com/security](https://myaccount.google.com/security)
2. Go to [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
3. Create a new app password (name it "YouTube Monitor" or anything you like)
4. Copy the 16-character password — you'll use it in the next step

### 5. Configure your .env file

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | From [aistudio.google.com](https://aistudio.google.com) |
| `GMAIL_ADDRESS` | Gmail address used to send reports |
| `GMAIL_APP_PASSWORD` | The 16-character app password from step 4 |
| `REPORT_RECIPIENT` | Email to receive reports (can be the same or different) |
| `BROWSER` | `chrome` or `firefox` |
| `HIGH_RISK_IMMEDIATE_ALERT` | `true` to get instant alerts for high-risk videos |
| `MAX_VIDEOS_PER_RUN` | How many videos to pull per run (default: 200) |

### 6. Initialize the database and run a test

```bash
python db.py        # Creates the SQLite database
python main.py      # Runs a full collection + analysis + email
```

The first run will pull and analyze up to `MAX_VIDEOS_PER_RUN` videos from watch history. Subsequent runs only process new videos.

Check your inbox — you should receive an email report.

### 7. Schedule daily runs

#### Windows (Task Scheduler)

Open PowerShell and run (update the paths for your machine):

```powershell
$action = New-ScheduledTaskAction -Execute "C:\path\to\venv\Scripts\python.exe" -Argument "C:\path\to\youtube-monitor\main.py" -WorkingDirectory "C:\path\to\youtube-monitor"
$trigger = New-ScheduledTaskTrigger -Daily -At "4:00AM"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "YouTubeMonitor" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest
```

`-StartWhenAvailable` means if your computer was off at 4 AM, the task will run as soon as it turns on.

#### macOS / Linux (cron)

```bash
crontab -e
```

Add this line (update paths):
```
0 4 * * * /path/to/venv/bin/python /path/to/youtube-monitor/main.py >> /path/to/youtube-monitor/logs/cron.log 2>&1
```

## Risk Classification

The AI uses Google Gemini 2.5 Flash with Islamic sensibilities. The key principle is **depiction ≠ endorsement** — a video that *features* something bad is not the same as a video that *glorifies* it.

| Risk | Meaning | Examples |
|---|---|---|
| 🔴 High | Harmful content is the *point* of the video | Explicit sexual content, glorifying drug use, gambling promotion, graphic gore, self-harm, hate speech, Islamophobic content, scams |
| 🟡 Medium | Worth a parent glance | Moderate profanity, teen intimacy, casual drug/alcohol normalization, suggestive content, intense horror |
| 🟢 Low | No action needed | Normal entertainment, gaming, music, sports, morally complex characters in stories, mild language |

High-risk videos trigger an immediate alert email in addition to the daily report.

## Limitations

- **Must run locally** — YouTube blocks transcript and audio downloads from datacenter IPs (AWS, GCP, Azure). This is not a bug or a fixable limitation; it's YouTube's deliberate policy. The tool only works reliably when run on a home machine with a residential IP address.
- **YouTube cookies expire** — typically every 2–4 months. When history stops being fetched, re-export your cookies using the Cookie-Editor extension.
- **Gemini free tier rate limit** — 15 requests/minute. The tool adds a 4.2-second delay between videos. A run with 100 new videos takes ~7 minutes.
- **Private/deleted videos** — videos deleted or made private after being watched will be analyzed by title only, with lower confidence.

## What About Google Cloud?

The code includes support for running as a Google Cloud Function (see [CLOUD_SETUP_AND_NOTES.md](CLOUD_SETUP_AND_NOTES.md)), but **it doesn't work well in practice** for the same reason as above: GCP IP addresses are blocked by YouTube, so neither transcript fetching nor audio download will work from the cloud. History collection still works, but you'd be classifying everything by title alone — which defeats the purpose.

**Recommendation: run it locally.** Windows Task Scheduler with `StartWhenAvailable` (see setup step 7) means it runs every morning as long as your computer turns on at some point during the day.

## Project Structure

| File | Purpose |
|---|---|
| `main.py` | Entry point — orchestrates the full pipeline |
| `collector.py` | Fetches YouTube watch history via InnerTube API |
| `enricher.py` | Downloads captions or audio for each video |
| `classifier.py` | Sends content to Gemini for risk analysis |
| `reporter.py` | Builds the HTML email report |
| `mailer.py` | Sends email via Gmail SMTP |
| `db.py` | SQLite database (deduplication + run history) |
| `config.py` | Reads config from `.env` or Secret Manager |

## Feedback & Community

If you set this up, I'd love to hear how it went — what worked, what didn't, what you'd change.

**[Start a Discussion →](https://github.com/adammosman/YoutubeMonitor/discussions)**

- Got it running? Share your setup in **Show and Tell**
- Something broken? Open an **Issue**
- Want a feature? Start a **Discussion** under Ideas

A ⭐ on the repo is also a simple way to let me know it was useful.

## License

MIT — do whatever you want with it.
