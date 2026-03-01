from google import genai
from google.genai import types
import config
import db
import time
import sys
import os
import json
import sqlite3

# Rate limiting for Gemini free tier (15 RPM -> 1 every 4 seconds)
DELAY_BETWEEN_CALLS = 4.2 

def init_client():
    api_key = config.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY not found in .env")
        return None
    return genai.Client(api_key=api_key)



def classify_video(client, video_title, channel_name, transcript_status, transcript_text, audio_path=None):
    """Sends video data to Gemini and requests structured JSON output."""
    
    uploaded_file = None
    contents_list = []
    
    # Construct the base text prompt
    prompt_text = f"""
    You are helping a Muslim parent monitor what their children watch on YouTube.
    Analyze the following YouTube video content and apply the risk framework described below.

    Title: {video_title}
    Channel: {channel_name}
    """
    
    # Add context depending on what we have (transcript vs audio vs nothing)
    if transcript_status == "success" and transcript_text:
        prompt_text += f"\nTranscript:\n{transcript_text[:15000]}"
        prompt_text += "\n\nGive a high confidence score if you can clearly determine the risk from the transcript."
        contents_list.append(prompt_text)
        
    elif audio_path and os.path.exists(audio_path):
        prompt_text += "\n\nI have attached the AUDIO TRACK of the video. You MUST listen to it carefully to determine the risk level."
        prompt_text += "\n\nDO NOT say the transcript is missing. Set your confidence score HIGH based on what you hear in the audio."
        
        try:
            print(f"Uploading audio file for analysis: {audio_path}")
            uploaded_file = client.files.upload(file=audio_path)
            
            # Wait for the file to be processed by Google before sending the prompt

            print("Waiting for audio file to process on Gemini servers...")
            timeout = 30
            start_time = time.time()
            
            while True:
                file_info = client.files.get(name=uploaded_file.name)
                if file_info.state.name == "ACTIVE":
                    break
                elif file_info.state.name == "FAILED":
                    raise Exception("Audio file processing failed on server side.")
                elif time.time() - start_time > timeout:
                    raise Exception("Audio file processing timed out.")
                time.sleep(2)
                
            contents_list.extend([file_info, prompt_text])
            
        except Exception as e:
            print(f"Failed to upload audio to Gemini: {e}")
            contents_list.append(prompt_text + "\n\n(Audio upload failed. Guess the risk based only on Title and Channel.)")
            
    else:
        prompt_text += "\nTranscript: [UNAVAILABLE - This might be a YouTube Short, music video, or lack subtitles]"
        prompt_text += "\n\nSince the transcript and audio are missing, you MUST give a low confidence score (<0.6). Guess the risk based only on the Title and Channel."
        contents_list.append(prompt_text)

    schema_instruction = """
    CRITICAL PRINCIPLE: Depiction is NOT the same as endorsement. A video that features bad
    behavior as part of a story, documentary, or news report is very different from a video that
    glorifies, promotes, or normalizes that behavior. When in doubt, lean LOW — only escalate
    when the harmful content is clearly central to the video's purpose or appeal.

    RISK LEVELS:

    HIGH RISK — Reserve for genuinely harmful content where the harmful element IS the point:
    - Explicit sexual content (visual, audio, extended description, or heavily sexualized content
      aimed at arousal)
    - Glorification of drug or alcohol use as cool, fun, or a desirable lifestyle (not mere depiction)
    - Gambling promoted as aspirational or easy money (e.g., sports betting "get rich" framing)
    - Graphic gore or extreme violence where the brutality itself is the entertainment (not action
      movie fights, gaming combat, or news coverage)
    - Self-harm or suicide presented non-therapeutically (romanticized, instructional, or as a solution)
    - Hate speech — content that dehumanizes people based on religion, race, ethnicity, or gender
    - Content mocking or disrespecting Islam, the Prophet (peace be upon him), the Quran, or
      Islamic practice in a mean-spirited or contemptuous way
    - Extreme profanity as the primary content — sexual or aggressive language dominating the video
    - Scam or fraud promotion — "easy money" schemes, fake giveaways, or predatory content
      targeting children
    - Body image or eating disorder content whose central purpose is glorifying dangerous thinness,
      encouraging restriction, or making viewers feel inadequate about their bodies
    - Conspiracy theories or dangerous health misinformation presented as the core message of the video
    - Occult or black magic presented as real, desirable, and a legitimate lifestyle (not clearly
      fictional entertainment)

    MEDIUM RISK — Worth a parent glance:
    - Moderate profanity — present throughout but not the dominant point of the video
    - Teenage romantic or intimate content — kissing scenes between teens, "dating as teenagers"
      framing, anything suggesting physical intimacy between minors
    - Casual drug or alcohol use shown without moral judgment (normalized, but not glorified)
    - Gambling depicted neutrally (a card game, sports betting casually referenced)
    - Immodest or suggestive content — sexualized but not explicit
    - Intense horror or disturbing imagery that could genuinely frighten children
    - Strong materialism or consumerism targeted at making children feel inadequate
    - Significant political extremism or divisive content pushing hatred

    LOW RISK — No action needed:
    - Normal entertainment, educational content, sports, cooking, gaming, music
    - Characters who are dishonest, mean, or morally flawed — this is normal storytelling; the
      question is whether the video glorifies that behavior, not whether it depicts it
    - Mild romantic content: dating, couples, mild affection, western-style relationships
    - News and documentaries covering difficult real-world topics
    - Cartoonish or stylized violence in games or animated content
    - Mild or occasional profanity
    - Pre-marital relationships depicted as normal in western culture (too ubiquitous to be useful
      as a flag; reserve for content actively promoting physical intimacy to teenagers)
    - Alcohol present but not the focus (e.g., wine in a cooking video, adults at a restaurant)
    - Music videos unless lyrics or visuals are explicitly sexual or glorify drugs/violence
    - Mildly crude humor

    PARENT ACTION:
    - "none"    → Low risk, no action needed
    - "discuss" → Low risk but touches on a topic worth a conversation (death, grief, divorce,
                  major life choices, religious questions)
    - "review"  → Medium risk, parent should read the summary or watch a clip
    - "alert"   → High risk, needs immediate parent attention

    Return a structured JSON object with:
    - risk_level (string): exactly "low", "medium", or "high"
    - categories (array of strings): content tags from this list where applicable:
      ["violence", "profanity", "sexual_content", "drug_use", "alcohol", "gambling",
       "self_harm", "hate_speech", "islamophobia", "scam", "misinformation", "occult",
       "body_image", "horror", "romance_teen", "romance_adult", "educational", "gaming",
       "music", "sports", "comedy", "news", "cooking", "lifestyle"]
    - confidence (float): 0.0 to 1.0 indicating certainty of this assessment
    - summary (string): 1-2 sentence description of what the video is actually about
    - rationale (string): why you assigned this risk level — specifically what content drove
      the decision; if LOW, briefly confirm it is benign
    - parent_action (string): "none", "discuss", "review", or "alert"
    """
    
    if isinstance(contents_list[0], str):
        contents_list[0] += f"\n{schema_instruction}"
    else:
        contents_list.append(schema_instruction)

    result = None
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=contents_list,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        
        # The response.text should be a valid JSON string

        result = json.loads(response.text)
        
    except Exception as e:
        print(f"Gemini API Error for '{video_title}': {e}")
        result = {
            "risk_level": "medium",
            "categories": ["error"],
            "confidence": 0.0,
            "summary": "AI classification failed.",
            "rationale": f"API Error: {str(e)}",
            "parent_action": "review"
        }
        
    finally:
        # Cleanup uploaded file from Google's servers
        if uploaded_file:
            try:
                client.files.delete(name=uploaded_file.name)
            except Exception as e:
                print(f"Failed to delete uploaded file from Gemini storage: {e}")
                
        # Cleanup local file
        if audio_path and os.path.exists(audio_path):
            try:
                os.remove(audio_path)
            except Exception as e:
                print(f"Failed to delete local audio file: {e}")

    return result

def analyze_new_videos(videos):
    """Iterates through enriched videos and classifies them using Gemini."""
    client = init_client()
    if not client:
        return []

    print(f"Starting classification for {len(videos)} videos...")
    
    analyzed_videos = []
    
    for i, video in enumerate(videos):
        # Skip if already analyzed in the DB (in case of resume)

        conn = sqlite3.connect(db.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM analysis WHERE video_id = ?", (video["video_id"],))
        exists = cursor.fetchone() is not None
        conn.close()
        
        if exists:
            print(f"Skipping {video['video_id']} - already analyzed.")
            continue

        safe_title = video['title'].encode(sys.stdout.encoding, errors='replace').decode(sys.stdout.encoding)
        print(f"Classifying [{i+1}/{len(videos)}]: {safe_title}")
        
        result = classify_video(
            client, 
            video["title"], 
            video["channel"],
            video.get("transcript_status", "unavailable"),
            video.get("transcript_text", ""),
            video.get("audio_path")
        )
        
        # Save to DB
        db.insert_analysis(
            video["video_id"],
            result.get("risk_level", "medium"),
            ",".join(result.get("categories", [])),
            result.get("summary", ""),
            result.get("confidence", 0.0),
            result.get("rationale", "")
        )
        
        # Merge results for the reporter
        video_copy = video.copy()
        video_copy.update(result)
        analyzed_videos.append(video_copy)
        
        # Respect Gemini free tier rate limits
        if i < len(videos) - 1:
            time.sleep(DELAY_BETWEEN_CALLS)
            
    return analyzed_videos
