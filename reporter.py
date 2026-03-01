from datetime import datetime
import config
import os

def render_video_block(v):
    # Determine icon and color based on risk
    risk = v.get("risk_level", "low").lower()
    color = "#4CAF50" # green
    icon = "🟢"
    if risk == "high":
        color = "#F44336" # red
        icon = "🔴"
    elif risk == "medium":
        color = "#FF9800" # orange
        icon = "🟡"
        
    transcript_status = v.get("transcript_status", "unavailable")
    if transcript_status == "success":
        analysis_note = ""
    elif v.get("audio_path") or v.get("audio_analyzed") or transcript_status in ("disabled", "blocked", "unavailable"):
        analysis_note = " <span style='color:#999; font-size:0.8em;'>(via audio)</span>"
    else:
        analysis_note = " <span style='color:#999; font-size:0.8em;'>(title only)</span>"
        
    categories = ", ".join(v.get("categories", []))
    
    # Format the watched time: prefer watched_at (YouTube day label or ISO), fall back to recorded_at
    watched_str = "Unknown"
    raw = v.get("watched_at") or v.get("recorded_at") or v.get("watched_label")
    if raw:
        try:
            dt = datetime.fromisoformat(raw)
            watched_str = dt.strftime("%b %d")
        except (ValueError, TypeError):
            watched_str = raw  # Already a label like "Yesterday", "Wednesday"

    html = f"""
    <div style="border-left: 4px solid {color}; padding-left: 15px; margin-bottom: 20px; background-color: #f9f9f9; padding: 10px;">
        <h3 style="margin-top: 0;">{icon} <a href="{v['url']}" style="color: #333; text-decoration: none;">{v['title']}</a></h3>
        <p style="color: #666; font-size: 0.9em; margin-bottom: 5px;">
            Channel: <b>{v['channel']}</b> | Watched: <b>{watched_str}</b> | Risk: <b>{risk.upper()}</b>
        </p>
        <p style="color: #666; font-size: 0.9em; margin-bottom: 5px;">Categories: <b>{categories}</b></p>
        <p>{v.get('summary', 'No summary available.')}{analysis_note}</p>
        <p style="font-size: 0.9em; color: #555;"><b>AI Rationale:</b> {v.get('rationale', '')}</p>
        <p style="font-size: 0.9em; color: #d32f2f;"><b>Suggested Action:</b> {v.get('parent_action', 'none').upper()}</p>
    </div>
    """
    return html

def render_low_risk_list(videos):
    if not videos:
        return ""
    
    html = "<ul>"
    for v in videos:
        html += f'<li><a href="{v["url"]}">{v["title"]}</a> (Channel: {v["channel"]})</li>'
    html += "</ul>"
    return html

def build_daily_report(analyzed_videos, errors=""):
    today = datetime.now().strftime("%Y-%m-%d")
    
    high_risk = [v for v in analyzed_videos if v.get("risk_level", "low").lower() == "high"]
    medium_risk = [v for v in analyzed_videos if v.get("risk_level", "low").lower() == "medium"]
    low_risk = [v for v in analyzed_videos if v.get("risk_level", "low").lower() == "low"]
    
    error_section = ""
    if errors:
        error_section = f'<div style="background-color: #ffebee; color: #c62828; padding: 10px; margin-bottom: 20px;"><b>System Alerts:</b><br/>{errors}</div>'

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto;">
        <h2>📺 YouTube Family Report - {today}</h2>
        {error_section}
        <p>Analyzed <b>{len(analyzed_videos)}</b> new videos today.</p>
        
        <div style="display: flex; gap: 20px; margin-bottom: 30px;">
            <div style="background: #ffebee; padding: 15px; border-radius: 5px; flex: 1; text-align: center;">
                <h3 style="margin: 0; color: #c62828;">{len(high_risk)}</h3>
                <span style="font-size: 0.8em;">High Risk</span>
            </div>
            <div style="background: #fff3e0; padding: 15px; border-radius: 5px; flex: 1; text-align: center;">
                <h3 style="margin: 0; color: #ef6c00;">{len(medium_risk)}</h3>
                <span style="font-size: 0.8em;">Medium Risk</span>
            </div>
            <div style="background: #e8f5e9; padding: 15px; border-radius: 5px; flex: 1; text-align: center;">
                <h3 style="margin: 0; color: #2e7d32;">{len(low_risk)}</h3>
                <span style="font-size: 0.8em;">Low Risk</span>
            </div>
        </div>
    """
    
    if high_risk:
        html += '<h3 style="color: #d32f2f; border-bottom: 2px solid #d32f2f; padding-bottom: 5px;">🔴 High Risk Videos</h3>'
        for v in high_risk:
            html += render_video_block(v)
            
    if medium_risk:
        html += '<h3 style="color: #f57c00; border-bottom: 2px solid #f57c00; padding-bottom: 5px;">🟡 Medium Risk Videos</h3>'
        for v in medium_risk:
            html += render_video_block(v)
            
    if low_risk:
        html += '<h3 style="color: #388e3c; border-bottom: 2px solid #388e3c; padding-bottom: 5px;">🟢 Low Risk Videos</h3>'
        html += render_low_risk_list(low_risk)
        
    html += """
        <hr style="border: 0; border-top: 1px solid #eee; margin-top: 30px;"/>
        <p style="font-size: 0.8em; color: #888; text-align: center;">Generated by YouTube History Monitor</p>
    </body>
    </html>
    """
    
    # Save a local copy
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%H%M")
    report_path = os.path.join(log_dir, f"report_{today}_{timestamp}.html")
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
        
    return html

def build_alert_email(video):
    """Specific immediate email for a newly discovered high-risk video."""
    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <h2 style="color: #d32f2f;">🚨 URGENT: High Risk Video Detected!</h2>
        <p>A video flagged as HIGH risk was just watched on the tracked YouTube account.</p>
        {render_video_block(video)}
    </body>
    </html>
    """
    return html
