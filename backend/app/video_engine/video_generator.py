from langgraph.graph import END, START, StateGraph
from langchain_core.runnables import RunnableLambda, RunnableParallel
import requests
from openai import OpenAI
import os
import time
from dotenv import load_dotenv
load_dotenv()
from typing import Dict, Any, List
from langchain_core.prompts import PromptTemplate
from gtts import gTTS
import json
from langchain_core.messages import HumanMessage
import base64
import subprocess
import whisper
import re
import random

# ============================================
# ANIMATION CONSTANTS (EXACT from images_to_video.py)
# ============================================
FPS = 60
WIDTH = 1080
HEIGHT = 1920
TRANSITION_DURATION = 1.0
MAX_ZOOM = 1.08
ZOOM_SPEED = 0.7


class VideoGenerator(Dict):
    user_query: str
    video_script: Any
    languages: List[str]
    style: str
    voice_overs: List[str]
    audio_files: List[str]
    image_files: List[str]
    scene_videos: List[str]
    scene_durations: List[float]  # Store durations for transition calculation
    all_word_segments: List[List[dict]]  # Store word segments for each scene for subtitle generation
    tts_lang: Any

def sanitize_model_json(text: str) -> str:
    """Remove ```json fences and extract the JSON object."""
    if not isinstance(text, str):
        return text

    t = text.strip()

    # Remove opening fence like ```json or ```
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t)

    # Remove closing fence ```
    t = re.sub(r"\s*```\s*$", "", t)

    t = t.strip()

    # Extract the first {...} block
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]

    return t

def generate_script(state: VideoGenerator) -> VideoGenerator:

    prompt_string = """
You are an expert political content creator and video editor. Your task is to generate a script for faceless vertical video (9:16).

Instructions:
- Split the script into scenes based on visual changes
- For each scene, provide the spoken text and 3 keywords for stock footage search
- Use an attention-grabbing 'Hook' in the first 3 seconds
- End with a 'Call to Action'
- Whatever the time is given by the user, divide the scenes into that time.
- you have to assign the expected time in seconds for each scene accrding to the length of the voiceover in each scene.
- Write the expected time in seconds for each scene according to the voiceover.
- There is no limit of scenes, you can create as many scenes as you want.
- In the voiceover you also have to write the tone, for eg: [excitedly] , [curiously], [delighted],[with genuine belly laugh],[giggling],[dramatically][impressed] etc. 
- Always write the tone in inside the '[]' bracket.
- IMPORTANT: Write ALL "voiceover" text strictly in {languages}. Do NOT use English (except proper nouns). Use the native script (e.g., हिन्दी, বাংলা, தமிழ்).
- Target language code: {tts_lang}. Use this to decide the exact language/script.
- ABSOLUTE RULE: The "voiceover" must be written ONLY in the target language's native script. 
  If tts_lang is "hi", use Devanagari only (हिन्दी). No Roman letters, no English words.

- Output strictly in JSON format with this structure:

{{
  "metadata": {{
    "topic": "<topic_name>",
    "language": "{languages}",
    "style": "{style}",
    "total_estimated_duration": "<duration>"
  }},
  "video_script": [
    {{
      "scene_id": 1,
      "expected_time_in_seconds": "expected_time_in_seconds",
      "voiceover": "spoken text",
      "visual_keywords": "keyword1, keyword2, keyword3",
      "overlay_text": "TEXT"
    }}
  ]
}}

Now generate a script for the following query:
{query}

Remember: Your response must be ONLY valid JSON, nothing else.
    """

    prompt = PromptTemplate(
    input_variables=["query", "languages", "style", "tts_lang"],
    template=prompt_string
    )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
        
    )

    response = client.chat.completions.create(
        model="google/gemini-2.5-flash-lite",
        messages=[
            {
                "role": "system",
                "content": "You are a video script generator. Always respond with valid JSON only. Follow the user's exact query topic."
            },
            {
                "role": "user",
                "content": prompt.format(
                    query=state["user_query"],
                    languages=", ".join(state.get("languages", [])) if isinstance(state.get("languages"), list) else str(state.get("languages", "")),
                    style=str(state.get("style", "")),
                    tts_lang=str(state.get("tts_lang", "en")),
                )
            }
        ],
        extra_body={"reasoning": {"enabled": True}}
    )
    script = response.choices[0].message.content
    script = sanitize_model_json(script)
    return {"video_script": script}


def extract_script(state: VideoGenerator) -> VideoGenerator:
    import re
    
    try:
        clean = sanitize_model_json(state["video_script"])
        script_data = json.loads(clean)
        voice_overs = []
        
        for scene in script_data.get("video_script", []):
            voiceover = scene.get("voiceover", "")
            if voiceover:
                voice_overs.append(voiceover)
        
        print(f"Extracted {len(voice_overs)} voiceovers")
        return {"voice_overs": voice_overs}
        print("tts_lang:", state.get("tts_lang"))
        print("voiceover sample:", voice_overs[0][:120] if voice_overs else "NONE")

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid script JSON: {state['video_script']}") from e


def generate_voice(state: VideoGenerator) -> VideoGenerator:
    voice_overs = state["voice_overs"]
    output_dir = "voice_outputs"
    os.makedirs(output_dir, exist_ok=True)
    audio_files = []
    

    tts_lang = state.get("tts_lang", "en")
    for idx, text in enumerate(voice_overs, start=1):
        filename = f"scene{idx}.mp3"
        filepath = os.path.join(output_dir, filename)
        clean_text = re.sub(r"\[[^\]]*\]", "", text).strip()
        clean_text = re.sub(r"\s+", " ", clean_text)
        tts = gTTS(text=clean_text, lang=tts_lang)
        tts.save(filepath)
        audio_files.append(filepath)

    state["audio_files"] = audio_files
    return state


def create_placeholder_image(output_path, text="Scene"):
    """Create a simple placeholder image using FFmpeg when image generation fails"""
    cmd = [
        'ffmpeg', '-y',
        '-f', 'lavfi',
        '-i', f'color=c=0x1a1a2e:s=1080x1920:d=1',
        '-vf', f"drawtext=text='{text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2",
        '-frames:v', '1',
        output_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        cmd_simple = [
            'ffmpeg', '-y',
            '-f', 'lavfi',
            '-i', 'color=c=0x1a1a2e:s=1080x1920:d=1',
            '-frames:v', '1',
            output_path
        ]
        subprocess.run(cmd_simple, check=True, capture_output=True)
        return True


def generate_image(state: VideoGenerator) -> VideoGenerator:

    image_files = []
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.getenv("OPENROUTER_API_KEY"),
    )

    output_dir = "scene_images"
    os.makedirs(output_dir, exist_ok=True)

    raw_script = state.get("video_script")

    if isinstance(raw_script, str):
        raw_script = raw_script.replace("Script:", "").strip()
        script_obj = json.loads(raw_script)
    elif isinstance(raw_script, dict):
        script_obj = raw_script
    else:
        raise ValueError("video_script must be str or dict")

    script_data = script_obj.get("video_script", [])

    MAX_RETRIES = 3

    for scene in script_data:
        scene_id = scene["scene_id"]
        voiceover = scene["voiceover"]
        keywords = scene["visual_keywords"]
        print(f"[*] Processing Scene {scene_id}")

        prompt_for_nemotron = (
            "Write a brief 20-word image prompt. "
            "Documentary style, no text, no faces."
            "The prompt should be on Indian context only."
            f"Topic: {keywords}"
        )

        try:
            nemotron_response = client.chat.completions.create(
                model="nvidia/nemotron-3-nano-30b-a3b:free",
                messages=[{"role": "user", "content": prompt_for_nemotron}],
                max_tokens=100
            )
            refined_prompt = nemotron_response.choices[0].message.content.strip()
            if len(refined_prompt) > 200:
                refined_prompt = refined_prompt[:200]
        except Exception as e:
            print(f"[!] Nemotron failed for Scene {scene_id}: {e}")
            refined_prompt = f"Documentary photo: {keywords}, realistic, no text, no faces"

        image_generated = False
        file_path = os.path.join(output_dir, f"scene_{scene_id}.jpg")

        for attempt in range(1, MAX_RETRIES + 1):
            print(f"    → Gemini attempt {attempt}")

            try:
                image_response = client.chat.completions.create(
                    model="google/gemini-2.5-flash-image",
                    messages=[{"role": "user", "content": refined_prompt}],
                    max_tokens=1024,
                    extra_body={"modalities": ["image", "text"]}
                )

                msg = image_response.choices[0].message

                if hasattr(msg, "images") and msg.images:
                    image_data_url = msg.images[0]["image_url"]["url"]
                    base64_str = image_data_url.split(",")[1]
                    image_bytes = base64.b64decode(base64_str)

                    with open(file_path, "wb") as f:
                        f.write(image_bytes)

                    print(f"[✓] Saved scene_{scene_id}.jpg")
                    image_generated = True
                    break
                    
            except Exception as e:
                error_msg = str(e)
                print(f"    [!] Attempt {attempt} failed: {error_msg}")
                
                if "402" in error_msg or "credit" in error_msg.lower():
                    print(f"    [!] Credit limit reached, creating placeholder image")
                    break
                
                time.sleep(1)

        if not image_generated:
            print(f"[!] Image generation failed for Scene {scene_id}, creating placeholder")
            if create_placeholder_image(file_path, f"Scene {scene_id}"):
                print(f"[✓] Created placeholder for scene_{scene_id}.jpg")
            
        image_files.append(file_path)
        
    state["image_files"] = image_files
    return state


def generate_in_parallel(state: VideoGenerator) -> VideoGenerator:

    voice_agent = RunnableLambda(generate_voice)
    image_agent = RunnableLambda(generate_image)

    parallel_agent = RunnableParallel(
        voice=voice_agent,
        image=image_agent
    )

    result = parallel_agent.invoke(state)

    final_state = state.copy()

    final_state.update(result["voice"])
    final_state.update(result["image"])

    return final_state

def normalize_whisper_lang(code):
    if not code:
        return None
    c = str(code).lower().strip()
    if "-" in c:  # hi-in -> hi
        c = c.split("-")[0]
    return c

def get_whisper_subtitles(audio_path, language=None):
    """Extract word-level timestamps using Whisper"""
    model = whisper.load_model("base")

    kwargs = {"word_timestamps": True}
    if language:
        kwargs["language"] = language
        kwargs["task"] = "transcribe"  # do NOT translate to English
        
        # Force Devanagari script for Hindi (prevents Urdu/Arabic script output)
        if language == "hi" or language=="hi-in":
            kwargs["initial_prompt"] = "हिंदी में देवनागरी लिपि में लिखें।"
        elif language == "mr" or language=="mr-in":
            kwargs["initial_prompt"] = "मराठी में देवनागरी लिपि में लिखें।"
        elif language == "gu" or language=="gu-in":
            kwargs["initial_prompt"] = "ગુજરાતી લિપિમાં લખો।"
        elif language == "bn" or language=="bn-in":
            kwargs["initial_prompt"] = "বাংলা লিপিতে লিখুন।"
        elif language == "ta" or language=="ta-in":
            kwargs["initial_prompt"] = "தமிழ் எழுத்துக்களில் எழுதுங்கள்।"
        elif language == "te" or language=="te-in":
            kwargs["initial_prompt"] = "తెలుగు లిపిలో వ్రాయండి।"

    result = model.transcribe(audio_path, **kwargs)

    word_segments = []
    for segment in result.get("segments", []):
        for word in segment.get("words", []) or []:
            word_segments.append({
                "word": word["word"].strip(),
                "start": word["start"],
                "end": word["end"]
            })
    return word_segments



def split_text_into_lines(text, max_width=40):
    """Split text into multiple lines for better readability"""
    words = text.split()
    lines = []
    current_line = []
    current_length = 0
    
    for word in words:
        if current_length + len(word) + 1 <= max_width:
            current_line.append(word)
            current_length += len(word) + 1
        else:
            if current_line:
                lines.append(' '.join(current_line))
            current_line = [word]
            current_length = len(word)
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return '\n'.join(lines)


def get_audio_duration(audio_path):
    """Get audio duration using ffprobe"""
    cmd = [
        'ffprobe', '-v', 'error',
        '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1',
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float(result.stdout.strip())


def escape_ass_text(text):
    """Escape special characters for ASS subtitle format"""
    text = text.replace('\n', '\\N')
    return text


def format_ass_time(seconds):
    """Convert seconds to ASS time format (H:MM:SS.cc)"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def generate_ass_subtitles(word_segments, output_path, audio_duration=None):
    """Generate ASS subtitle file with word-by-word color highlighting - continuous display"""
    
    if not word_segments:
        return output_path
    
    HIGHLIGHT_COLOR = "&H00FFFF&"
    NORMAL_COLOR = "&HFFFFFF&"
    
    ass_header = """[Script Info]
Title: Video Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,52,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1.5,2,40,40,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    words_list = [w['word'] for w in word_segments]
    
    first_word_start = word_segments[0]['start']
    last_word_end = word_segments[-1]['end']
    
    if audio_duration:
        last_word_end = max(last_word_end, audio_duration)
    
    for idx, word_data in enumerate(word_segments):
        start_time = word_data['start']
        
        if idx < len(word_segments) - 1:
            end_time = word_segments[idx + 1]['start']
        else:
            end_time = last_word_end
        
        if end_time <= start_time:
            end_time = start_time + 0.1
        
        colored_words = []
        
        for i, word in enumerate(words_list):
            if i == idx:
                colored_words.append(f"{{\\c{HIGHLIGHT_COLOR}\\b1\\fscx110\\fscy110}}{word.upper()}{{\\c{NORMAL_COLOR}\\b0\\fscx100\\fscy100}}")
            else:
                colored_words.append(word)
        
        full_text = ' '.join(colored_words)
        wrapped_text = smart_wrap_with_tags(full_text, max_width=35)
        escaped_text = escape_ass_text(wrapped_text)
        
        start_str = format_ass_time(start_time)
        end_str = format_ass_time(end_time)
        
        events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_text}")
    
    if first_word_start > 0.1:
        all_white = ' '.join(words_list)
        wrapped_intro = smart_wrap_with_tags(all_white, max_width=35)
        escaped_intro = escape_ass_text(wrapped_intro)
        start_str = format_ass_time(0)
        end_str = format_ass_time(first_word_start)
        events.insert(0, f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_intro}")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(ass_header)
        f.write('\n'.join(events))
    
    return output_path


def smart_wrap_with_tags(text, max_width=35):
    """Wrap text into lines while preserving ASS formatting tags"""
    parts = text.split(' ')
    lines = []
    current_line = []
    current_visible_length = 0
    
    for part in parts:
        visible_part = re.sub(r'\{[^}]*\}', '', part)
        visible_length = len(visible_part)
        
        if current_visible_length + visible_length + 1 <= max_width or not current_line:
            current_line.append(part)
            current_visible_length += visible_length + 1
        else:
            lines.append(' '.join(current_line))
            current_line = [part]
            current_visible_length = visible_length + 1
    
    if current_line:
        lines.append(' '.join(current_line))
    
    return '\\N'.join(lines)


# ============================================
# ANIMATION-INTEGRATED SCENE BUILDING
# (Exact zoom logic from images_to_video.py)
# ============================================

def combine_scene_with_animation(image_path, audio_path, output_path, scene_idx, is_extended=False,tts_lang=None):
    """
    Combine image and audio with:
    1. Zoom animation (EXACT from images_to_video.py)
    2. NO subtitles here - subtitles applied after final stitch
    
    Args:
        image_path: Path to scene image
        audio_path: Path to scene audio
        output_path: Output video path
        scene_idx: Scene index (0-based)
        is_extended: If True, extend video duration by TRANSITION_DURATION for xfade
    
    Returns:
        tuple: (audio_duration, word_segments) for subtitle generation
    """
    
    # Get audio duration
    audio_duration = get_audio_duration(audio_path)
    
    # EXACT LOGIC FROM images_to_video.py:
    # Extend all clips except first by transition duration
    if is_extended and scene_idx > 0:
        video_duration = audio_duration + TRANSITION_DURATION
    else:
        video_duration = audio_duration
    
    frames = int(video_duration * FPS)
    zoom_frames = int(frames * ZOOM_SPEED)
    
    # EXACT ZOOM LOGIC FROM images_to_video.py:
    # Random zoom in or zoom out
    start_zoom, end_zoom = random.choice([
        (1.00, MAX_ZOOM),
        (MAX_ZOOM, 1.00)
    ])
    
    # EXACT ZOOM EXPRESSION FROM images_to_video.py:
    zoom_expr = (
        f"if(lte(n\\,{zoom_frames})\\,"
        f"{start_zoom}+({end_zoom-start_zoom})*"
        f"(1-cos(PI*n/{zoom_frames}))/2\\,"
        f"{end_zoom})"
    )
    
    # Get word-level timestamps from Whisper (for later subtitle generation)
    lang_for_whisper = normalize_whisper_lang(tts_lang)  # use the function argument
    word_segments = get_whisper_subtitles(audio_path, language=lang_for_whisper)

    
    # EXACT VIDEO FILTER FROM images_to_video.py (NO SUBTITLES - applied after stitch):
    vf = (
        f"scale='max({WIDTH},iw)':'max({HEIGHT},ih)',"
        f"scale=iw*({zoom_expr}):ih*({zoom_expr}):eval=frame,"
        f"crop={WIDTH}:{HEIGHT}:(iw-{WIDTH})/2:(ih-{HEIGHT})/2"
    )
    
    # FFmpeg command combining image + audio + zoom (no subtitles)
    cmd = [
        'ffmpeg', '-y',
        '-loop', '1',
        '-i', image_path,
        '-i', audio_path,
        '-vf', vf,
        '-t', str(video_duration),
        '-r', str(FPS),
        '-pix_fmt', 'yuv420p',
        '-c:v', 'libx264',
        '-preset', 'fast',
        '-crf', '23',
        '-c:a', 'aac',
        '-b:a', '192k',
        output_path
    ]
    
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    print(f"[✓] Created scene {scene_idx + 1} with animation: {output_path} ({video_duration:.2f}s)")
    
    return audio_duration, word_segments  # Return both for subtitle generation


def build_scenes(state: VideoGenerator) -> VideoGenerator:
    """Build individual scene videos with zoom animation"""
    
    video_dir = "scene_videos"
    os.makedirs(video_dir, exist_ok=True)

    audio_files = state["audio_files"]
    image_files = state["image_files"]

    scene_videos = []
    scene_durations = []
    all_word_segments = []  # Store word segments for each scene

    total_scenes = min(len(audio_files), len(image_files))

    print(f"\n🎬 Creating {total_scenes} clips with zoom animations...")

    for idx in range(total_scenes):
        audio_path = audio_files[idx]
        image_path = image_files[idx]

        output_path = os.path.join(video_dir, f"scene_{idx+1}.mp4")

        if not os.path.exists(audio_path) or not os.path.exists(image_path):
            print(f"[!] Missing assets for Scene {idx+1}, skipping")
            continue

        # Build scene with animation
        # Extend non-first clips for smooth xfade transitions
        base_duration, word_segments = combine_scene_with_animation(
            image_path=image_path,
            audio_path=audio_path,
            output_path=output_path,
            scene_idx=idx,
            is_extended=True,  # Enable extension for xfade
            tts_lang=state.get("tts_lang", "en"),
        )

        scene_videos.append(output_path)
        scene_durations.append(base_duration)
        all_word_segments.append(word_segments)

    state["scene_videos"] = scene_videos
    state["scene_durations"] = scene_durations
    state["all_word_segments"] = all_word_segments  # Store for subtitle generation
    return state


# ============================================
# ANIMATION-INTEGRATED FINAL STITCHING
# (Exact xfade logic from images_to_video.py)
# ============================================

def generate_combined_ass_subtitles(all_word_segments, scene_durations, output_path):
    """
    Generate a single ASS subtitle file for the entire video
    with proper time offsets for each scene
    """
    
    HIGHLIGHT_COLOR = "&H00FFFF&"
    NORMAL_COLOR = "&HFFFFFF&"
    
    ass_header = """[Script Info]
Title: Video Subtitles
ScriptType: v4.00+
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial Black,52,&H00FFFFFF,&H000000FF,&H00000000,&H96000000,-1,0,0,0,100,100,0,0,1,3,1.5,2,40,40,480,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    
    events = []
    cumulative_offset = 0.0
    
    for scene_idx, word_segments in enumerate(all_word_segments):
        if not word_segments:
            # No words in this scene, just add the duration offset
            if scene_idx < len(scene_durations):
                cumulative_offset += scene_durations[scene_idx]
            continue
        
        words_list = [w['word'] for w in word_segments]
        scene_duration = scene_durations[scene_idx] if scene_idx < len(scene_durations) else 5.0
        
        first_word_start = word_segments[0]['start']
        last_word_end = word_segments[-1]['end']
        
        # Extend to scene duration if needed
        last_word_end = max(last_word_end, scene_duration)
        
        # Add initial subtitle before first word (all white)
        if first_word_start > 0.1:
            all_white = ' '.join(words_list)
            wrapped_intro = smart_wrap_with_tags(all_white, max_width=35)
            escaped_intro = escape_ass_text(wrapped_intro)
            start_str = format_ass_time(cumulative_offset)
            end_str = format_ass_time(cumulative_offset + first_word_start)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_intro}")
        
        # Generate word-by-word highlighting
        for idx, word_data in enumerate(word_segments):
            start_time = cumulative_offset + word_data['start']
            
            if idx < len(word_segments) - 1:
                end_time = cumulative_offset + word_segments[idx + 1]['start']
            else:
                end_time = cumulative_offset + last_word_end
            
            if end_time <= start_time:
                end_time = start_time + 0.1
            
            colored_words = []
            for i, word in enumerate(words_list):
                if i == idx:
                    colored_words.append(f"{{\\c{HIGHLIGHT_COLOR}\\b1\\fscx110\\fscy110}}{word.upper()}{{\\c{NORMAL_COLOR}\\b0\\fscx100\\fscy100}}")
                else:
                    colored_words.append(word)
            
            full_text = ' '.join(colored_words)
            wrapped_text = smart_wrap_with_tags(full_text, max_width=35)
            escaped_text = escape_ass_text(wrapped_text)
            
            start_str = format_ass_time(start_time)
            end_str = format_ass_time(end_time)
            
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_text}")
        
        # Add this scene's duration to offset for next scene
        cumulative_offset += scene_duration
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(ass_header)
        f.write('\n'.join(events))
    
    return output_path


def stitch_final_video(state: VideoGenerator, output_file="final_video.mp4"):
    """
    Concatenate scene videos with xfade transitions for VIDEO ONLY
    Audio is concatenated sequentially (no overlap)
    Subtitles are applied AFTER stitching to avoid overlap
    """
    
    scene_videos = state["scene_videos"]
    scene_durations = state.get("scene_durations", [])
    all_word_segments = state.get("all_word_segments", [])
    
    if not scene_videos:
        print("[!] No scene videos to stitch")
        return state
    
    os.makedirs("outputs/video", exist_ok=True)
    
    # Intermediate file (without subtitles)
    temp_output = "temp_stitched_no_subs.mp4"
    
    # If only one clip, just copy it
    if len(scene_videos) == 1:
        subprocess.run(
            ['ffmpeg', '-y', '-i', scene_videos[0], '-c', 'copy', temp_output],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        print(f"\n🔗 Merging {len(scene_videos)} scenes with crossfade transitions...")
        
        # Build inputs
        inputs = []
        for clip in scene_videos:
            inputs += ['-i', clip]
        
        # ============================================
        # VIDEO: xfade transitions (EXACT from images_to_video.py)
        # AUDIO: Simple concatenation (NO overlap)
        # ============================================
        
        filter_complex = ""
        
        # --- VIDEO XFADE CHAIN ---
        prev_video_label = "0:v"
        cumulative_time = scene_durations[0] if scene_durations else get_audio_duration(state["audio_files"][0])
        
        for i in range(1, len(scene_videos)):
            current_video_label = f"v{i}"
            
            # EXACT OFFSET CALCULATION FROM images_to_video.py:
            offset = cumulative_time - TRANSITION_DURATION
            
            # Video xfade (EXACT from images_to_video.py)
            filter_complex += (
                f"[{prev_video_label}][{i}:v]"
                f"xfade=transition=fade:"
                f"duration={TRANSITION_DURATION}:"
                f"offset={offset}"
                f"[{current_video_label}];"
            )
            
            prev_video_label = current_video_label
            
            # Accumulate duration for next offset calculation
            if i < len(scene_durations):
                cumulative_time += scene_durations[i]
        
        # --- AUDIO CONCATENATION (NO OVERLAP) ---
        audio_labels = []
        for i in range(len(scene_videos)):
            duration = scene_durations[i] if i < len(scene_durations) else 5.0
            audio_label = f"a{i}trimmed"
            filter_complex += f"[{i}:a]atrim=0:{duration},asetpts=PTS-STARTPTS[{audio_label}];"
            audio_labels.append(f"[{audio_label}]")
        
        filter_complex += f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[aout]"
        
        # FFmpeg command - create video WITHOUT subtitles first
        cmd = (
            ['ffmpeg', '-y']
            + inputs
            + [
                '-filter_complex', filter_complex,
                '-map', f'[{prev_video_label}]',
                '-map', '[aout]',
                '-r', str(FPS),
                '-pix_fmt', 'yuv420p',
                '-c:v', 'libx264',
                '-preset', 'fast',
                '-crf', '23',
                '-c:a', 'aac',
                '-b:a', '192k',
                temp_output
            ]
        )
        
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # ============================================
    # APPLY SUBTITLES TO FINAL VIDEO
    # ============================================
    print("\n📝 Applying subtitles to final video...")
    
    if all_word_segments and any(all_word_segments):
        # Generate combined subtitle file
        subtitle_dir = "temp_subtitles"
        os.makedirs(subtitle_dir, exist_ok=True)
        subtitle_path = os.path.join(subtitle_dir, "combined_subtitles.ass")
        generate_combined_ass_subtitles(all_word_segments, scene_durations, subtitle_path)
        
        # Escape path for FFmpeg filter
        escaped_subtitle_path = subtitle_path.replace('\\', '/').replace(':', '\\:').replace("'", "\\'")
        
        # Burn subtitles into final video
        cmd = [
            'ffmpeg', '-y',
            '-i', temp_output,
            '-vf', f"ass='{escaped_subtitle_path}'",
            '-c:v', 'libx264',
            '-preset', 'fast',
            '-crf', '23',
            '-c:a', 'copy',
            output_file
        ]
        
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Clean up temp file
        if os.path.exists(temp_output):
            os.remove(temp_output)
    else:
        # No subtitles, just rename temp to final
        os.rename(temp_output, output_file)
    
    # ============================================
    # DURATION VERIFICATION
    # ============================================
    expected_duration = sum(scene_durations) if scene_durations else 0
    
    result = subprocess.run(
        [
            'ffprobe', '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            output_file
        ],
        capture_output=True,
        text=True,
        check=True
    )
    
    actual_duration = float(result.stdout.strip())
    
    print(f"\n{'='*60}")
    print(f"VIDEO CREATION SUMMARY")
    print(f"{'='*60}")
    print(f"Expected duration: {expected_duration:.2f}s")
    print(f"Actual duration: {actual_duration:.2f}s")
    print(f"Difference: {abs(actual_duration - expected_duration):.2f}s")
    print(f"Status: {'✅ PERFECT' if abs(actual_duration - expected_duration) < 0.5 else '⚠️ CHECK'}")
    print(f"{'='*60}\n")
    
    print(f"[✓] Final video created: {output_file}")
    
    return state


# ============================================
# LANGGRAPH WORKFLOW
# ============================================

workflow = StateGraph(VideoGenerator)
workflow.add_node("generate_script", generate_script)
workflow.add_node("extract_script", extract_script)
workflow.add_node("generate_in_parallel", generate_in_parallel)
workflow.add_node("build_scenes", build_scenes)
workflow.add_node("stitch_final_video", stitch_final_video)
workflow.add_edge("generate_script", "extract_script")
workflow.add_edge("extract_script", "generate_in_parallel")
workflow.add_edge("generate_in_parallel", "build_scenes")
workflow.add_edge("build_scenes", "stitch_final_video")
workflow.add_edge("stitch_final_video", END)
workflow.add_edge(START, "generate_script")
app = workflow.compile()


if __name__ == "__main__":
    inputs = {
        "user_query": "Generate me the script on Naxalism in India for 60 seconds in English language.",
        "languages": ["English"],
        "style": "Cinematic",
        "tts_lang": "en",
    }
    final_state = app.invoke(inputs)
    script = final_state["video_script"]
    voice_overs = final_state["voice_overs"]
    print("Script:", script)
    print("Voiceovers:", voice_overs)
    print("Type of Voiceovers:", type(voice_overs))
    print("Audio Files:", final_state["audio_files"])
    print("Image Files:", final_state["image_files"])
    print("Scene Videos:", final_state["scene_videos"])
    print("Scene Durations:", final_state["scene_durations"])
    print("Word Segments per Scene:", [len(ws) for ws in final_state.get("all_word_segments", [])])