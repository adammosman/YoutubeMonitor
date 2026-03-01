import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass

import db
import config
import collector
import enricher
import classifier
import reporter
import mailer
import time
from datetime import datetime
import functions_framework

@functions_framework.http
def cloud_entry(request):
    """HTTP Cloud Function entry point triggered by Cloud Scheduler."""
    try:
        db.download_db_from_cloud()
        main()
        db.upload_db_to_cloud()
        return "OK", 200
    except Exception as e:
        import traceback
        error_msg = traceback.format_exc()
        print(f"CLOUD FUNCTION ERROR: {error_msg}")
        try:
            mailer.send_email("⚠️ YouTube Monitor CRASHED", f"<pre>{error_msg}</pre>")
        except:
            pass
        db.upload_db_to_cloud()  # Still save progress
        return f"Error: {str(e)}", 500

def main():
    print(f"=== Starting YouTube History Monitor Run: {datetime.now()} ===")
    
    # 1. Initialize
    db.init_db()
    run_id = db.start_run()
    browser = config.get("BROWSER", "chrome")
    max_videos = int(config.get("MAX_VIDEOS_PER_RUN", 200))
    send_immediate_alerts = config.get("HIGH_RISK_IMMEDIATE_ALERT", "true").lower() == "true"
    
    # 2. Check for Resume State
    print("\n--- PHASE 1: Collection ---")
    unanalyzed_backlog = db.get_unanalyzed_videos()
    
    if unanalyzed_backlog:
        print(f"Found {len(unanalyzed_backlog)} unanalyzed videos in the database from a previous failed or partial run.")
        print("Skipping YouTube API collection and resuming analysis...")
        new_videos = unanalyzed_backlog
        
        # Important: Even when resuming, we must pull cookies so yt-dlp has them to download audio
        collector.get_youtube_cookies(browser)
    else:
        # Proceed with normal collection if no backlog exists
        collection_result = collector.run_collection(browser, max_videos)
        
        if collection_result["error"] == "cookie_failure":
            error_msg = f"Failed to extract {browser} cookies. Are you logged out of YouTube?"
            print(error_msg)
            mailer.send_email("⚠️ YouTube Monitor Alert: Authentication Failed", error_msg)
            db.finish_run(run_id, "failed", 0, error_msg)
            return
            
        if collection_result["error"] == "api_failure":
            error_msg = "Failed to fetch from YouTube InnerTube API."
            print(error_msg)
            db.finish_run(run_id, "failed", 0, error_msg)
            return
            
        new_videos = collection_result["videos"]
        if not new_videos:
            print("No new videos found. Exiting.")
            db.finish_run(run_id, "success", 0)
            return
        
    # 3 & 4. Sequence Processing (Enrich + Classify safely within Cloud limits)
    print("\n--- PHASE 2 & 3: Enrichment & Classification ---")
    analyzed_videos = []
    
    start_time = time.time()
    # Cloud functions have a 9-minute hard limit; local runs have no constraint
    is_cloud = bool(config.get("GCS_BUCKET"))
    MAX_EXECUTION_TIME = 450 if is_cloud else float('inf')
    
    for i, video in enumerate(new_videos):
        elapsed = time.time() - start_time
        if elapsed > MAX_EXECUTION_TIME:
            print(f"⚠️ Reached 7.5 minute execution limit ({int(elapsed)}s). Stopping at video {i}.")
            print(f"The remaining {len(new_videos)-i} videos will be analyzed on the next scheduled run.")
            break
            
        print(f"\nProcessing [{i+1}/{len(new_videos)}]: {video['title']}")
        
        # A. Enrich (fetch transcript or audio)
        enriched = enricher.enrich_videos([video])
        
        # B. Classify with Gemini
        analyzed = classifier.analyze_new_videos(enriched)
        
        if analyzed:
            final_vid = analyzed[0]
            analyzed_videos.append(final_vid)
            
            # C. Immediate Alerts
            if send_immediate_alerts and final_vid.get("risk_level", "low").lower() == "high":
                alert_html = reporter.build_alert_email(final_vid)
                mailer.send_email(f"🚨 High Risk Video Detected", alert_html)
                
        # D. Respect Gemini free tier rate limits (15 RPM)
        if i < len(new_videos) - 1:
            time.sleep(classifier.DELAY_BETWEEN_CALLS)
    
    # 5. Build and Send Daily Report
    print("\n--- PHASE 4: Reporting ---")
    report_html = reporter.build_daily_report(analyzed_videos)
    
    subject = f"YouTube Family Report ({len(analyzed_videos)} videos)"
    
    high_risk_count = len([v for v in analyzed_videos if v.get("risk_level", "low").lower() == "high"])
    if high_risk_count > 0:
        subject += f" - {high_risk_count} 🔴 HIGH RISK"
        
    email_sent = mailer.send_email(subject, report_html)
    
    if email_sent:
        print("Run completed successfully.")
        db.finish_run(run_id, "success", len(analyzed_videos))
    else:
        print("Run completed, but failed to send email report.")
        db.finish_run(run_id, "failed_email", len(analyzed_videos), "Failed to send email.")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        import os
        
        error_msg = traceback.format_exc()
        print(f"FATAL ERROR: {e}")
        print(error_msg)
        
        # Log to file so Task Scheduler failures are visible
        log_dir = os.path.join(os.path.dirname(__file__), "logs")
        os.makedirs(log_dir, exist_ok=True)
        crash_path = os.path.join(log_dir, f"crash_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
        with open(crash_path, "w", encoding="utf-8") as f:
            f.write(error_msg)
        
        # Try to send error notification
        try:
            mailer.send_email(
                "⚠️ YouTube Monitor CRASHED",
                f"<pre>{error_msg}</pre>"
            )
        except:
            pass
