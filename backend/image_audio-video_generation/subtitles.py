# subtitles.py
import re
from typing import Any, Dict, List, Optional


# -------------------------------------------------
# Whisper helpers
# -------------------------------------------------
def normalize_whisper_lang(code: Optional[str]) -> Optional[str]:
    if not code:
        return None
    c = str(code).lower().strip()
    if "-" in c:  # hi-in -> hi
        c = c.split("-")[0]
    return c


# Optional: regional-language fallback if you supply expected_text + audio_duration
REGIONAL_LANG_PREFIXES = {
    "hi", "mr", "bn", "ta", "te", "gu", "kn", "ml", "or", "pa", "kok", "mai", "sd", "ur", "as"
}


def _clean_voiceover_text(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"\[[^\]]*\]", "", text).strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _tokenize_for_subtitles(text: str) -> List[str]:
    if not text:
        return []
    tokens = text.split()
    cleaned = []
    for tok in tokens:
        tok2 = tok.strip(" \t\n\r,.;:!?\"'“”‘’()[]{}<>|—–-…।॥")
        if tok2:
            cleaned.append(tok2)
    return cleaned


def _approx_word_segments_from_text(expected_text: str, audio_duration: float) -> List[dict]:
    expected_text = _clean_voiceover_text(expected_text)
    words = _tokenize_for_subtitles(expected_text)
    if not words or not audio_duration or audio_duration <= 0:
        return []

    weights = [max(1, len(w)) for w in words]
    total_w = float(sum(weights)) if weights else 1.0

    MIN_D = 0.06
    segments = []
    t = 0.0

    for w, wt in zip(words, weights):
        d = max(MIN_D, audio_duration * (wt / total_w))
        start = t
        end = min(audio_duration, start + d)
        if end <= start:
            end = min(audio_duration, start + MIN_D)
        segments.append({"word": w, "start": start, "end": end})
        t = end

    if segments:
        segments[-1]["end"] = max(segments[-1]["end"], audio_duration)

    return segments


def get_whisper_subtitles(
    audio_path: str,
    language: Optional[str] = None,
    expected_text: Optional[str] = None,
    audio_duration: Optional[float] = None,
) -> List[dict]:
    """
    Default behavior (same as your monolith):
    - Uses Whisper word_timestamps output.

    Optional improvement (does NOT break existing calls):
    - If expected_text + audio_duration are provided AND language is regional,
      it will generate accurate word segments from transcript (avoids Whisper mistakes).
    """
    lang_norm = normalize_whisper_lang(language)

    if expected_text and audio_duration and lang_norm in REGIONAL_LANG_PREFIXES:
        return _approx_word_segments_from_text(expected_text, audio_duration)

    import whisper  # keep local to reduce import load at startup

    model = whisper.load_model("base")

    kwargs: Dict[str, Any] = {"word_timestamps": True}
    if language:
        kwargs["language"] = language
        kwargs["task"] = "transcribe"  # do NOT translate to English

        # Your original script-forcing prompts
        if language == "hi" or language == "hi-in":
            kwargs["initial_prompt"] = "हिंदी में देवनागरी लिपि में लिखें।"
        elif language == "mr" or language == "mr-in":
            kwargs["initial_prompt"] = "मराठी में देवनागरी लिपि में लिखें।"
        elif language == "gu" or language == "gu-in":
            kwargs["initial_prompt"] = "ગુજરાતી લિપિમાં લખો।"
        elif language == "bn" or language == "bn-in":
            kwargs["initial_prompt"] = "বাংলা লিপিতে লিখুন।"
        elif language == "ta" or language == "ta-in":
            kwargs["initial_prompt"] = "தமிழ் எழுத்துக்களில் எழுதுங்கள்।"
        elif language == "te" or language == "te-in":
            kwargs["initial_prompt"] = "తెలుగు లిపిలో వ్రాయండి।"

    result = model.transcribe(audio_path, **kwargs)

    word_segments = []
    for segment in result.get("segments", []):
        for word in segment.get("words", []) or []:
            word_segments.append(
                {"word": word["word"].strip(), "start": word["start"], "end": word["end"]}
            )
    return word_segments


# -------------------------------------------------
# ASS subtitle generation (same logic as your monolith)
# -------------------------------------------------
def escape_ass_text(text: str) -> str:
    text = text.replace("\n", "\\N")
    return text


def format_ass_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def smart_wrap_with_tags(text: str, max_width: int = 35) -> str:
    """Wrap text into lines while preserving ASS formatting tags"""
    parts = text.split(" ")
    lines = []
    current_line = []
    current_visible_length = 0

    for part in parts:
        visible_part = re.sub(r"\{[^}]*\}", "", part)
        visible_length = len(visible_part)

        if current_visible_length + visible_length + 1 <= max_width or not current_line:
            current_line.append(part)
            current_visible_length += visible_length + 1
        else:
            lines.append(" ".join(current_line))
            current_line = [part]
            current_visible_length = visible_length + 1

    if current_line:
        lines.append(" ".join(current_line))

    return "\\N".join(lines)


def generate_ass_subtitles(word_segments: List[dict], output_path: str, audio_duration: Optional[float] = None) -> str:
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
    words_list = [w["word"] for w in word_segments]

    first_word_start = word_segments[0]["start"]
    last_word_end = word_segments[-1]["end"]

    if audio_duration:
        last_word_end = max(last_word_end, audio_duration)

    for idx, word_data in enumerate(word_segments):
        start_time = word_data["start"]

        if idx < len(word_segments) - 1:
            end_time = word_segments[idx + 1]["start"]
        else:
            end_time = last_word_end

        if end_time <= start_time:
            end_time = start_time + 0.1

        colored_words = []
        for i, word in enumerate(words_list):
            if i == idx:
                colored_words.append(
                    f"{{\\c{HIGHLIGHT_COLOR}\\b1\\fscx110\\fscy110}}{word.upper()}{{\\c{NORMAL_COLOR}\\b0\\fscx100\\fscy100}}"
                )
            else:
                colored_words.append(word)

        full_text = " ".join(colored_words)
        wrapped_text = smart_wrap_with_tags(full_text, max_width=35)
        escaped_text = escape_ass_text(wrapped_text)

        start_str = format_ass_time(start_time)
        end_str = format_ass_time(end_time)

        events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_text}")

    if first_word_start > 0.1:
        all_white = " ".join(words_list)
        wrapped_intro = smart_wrap_with_tags(all_white, max_width=35)
        escaped_intro = escape_ass_text(wrapped_intro)
        start_str = format_ass_time(0)
        end_str = format_ass_time(first_word_start)
        events.insert(0, f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_intro}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        f.write("\n".join(events))

    return output_path


def generate_combined_ass_subtitles(
    all_word_segments: List[List[dict]],
    scene_durations: List[float],
    output_path: str,
) -> str:
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
            if scene_idx < len(scene_durations):
                cumulative_offset += scene_durations[scene_idx]
            continue

        words_list = [w["word"] for w in word_segments]
        scene_duration = scene_durations[scene_idx] if scene_idx < len(scene_durations) else 5.0

        first_word_start = word_segments[0]["start"]
        last_word_end = word_segments[-1]["end"]
        last_word_end = max(last_word_end, scene_duration)

        if first_word_start > 0.1:
            all_white = " ".join(words_list)
            wrapped_intro = smart_wrap_with_tags(all_white, max_width=35)
            escaped_intro = escape_ass_text(wrapped_intro)
            start_str = format_ass_time(cumulative_offset)
            end_str = format_ass_time(cumulative_offset + first_word_start)
            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_intro}")

        for idx, word_data in enumerate(word_segments):
            start_time = cumulative_offset + word_data["start"]

            if idx < len(word_segments) - 1:
                end_time = cumulative_offset + word_segments[idx + 1]["start"]
            else:
                end_time = cumulative_offset + last_word_end

            if end_time <= start_time:
                end_time = start_time + 0.1

            colored_words = []
            for i, word in enumerate(words_list):
                if i == idx:
                    colored_words.append(
                        f"{{\\c{HIGHLIGHT_COLOR}\\b1\\fscx110\\fscy110}}{word.upper()}{{\\c{NORMAL_COLOR}\\b0\\fscx100\\fscy100}}"
                    )
                else:
                    colored_words.append(word)

            full_text = " ".join(colored_words)
            wrapped_text = smart_wrap_with_tags(full_text, max_width=35)
            escaped_text = escape_ass_text(wrapped_text)

            start_str = format_ass_time(start_time)
            end_str = format_ass_time(end_time)

            events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{escaped_text}")

        cumulative_offset += scene_duration

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(ass_header)
        f.write("\n".join(events))

    return output_path
