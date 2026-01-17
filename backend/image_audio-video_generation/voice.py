# voice.py
import os
import json
import re
import random
import subprocess
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

# --------------------------------------------
# ENV
# --------------------------------------------
ELEVEN_API_KEY = (os.getenv("ELEVEN_API_KEY") or "").strip().strip('"').strip("'")
ELEVEN_OUTPUT_FORMAT = (os.getenv("ELEVEN_OUTPUT_FORMAT") or "mp3_44100_128").strip()
ELEVEN_MODEL_ID = (os.getenv("ELEVEN_MODEL_ID") or "eleven_v3").strip()  # v3 supports audio tags

# Voice pools file path (JSON-like)
ELEVEN_VOICE_POOLS_PATH = (os.getenv("ELEVEN_VOICE_POOLS_PATH") or "voice_pools.json").strip()

# Optional fallbacks (if a language pool is missing)
ELEVEN_DEFAULT_MALE_VOICE_ID = (os.getenv("ELEVEN_DEFAULT_MALE_VOICE_ID") or "").strip()
ELEVEN_DEFAULT_FEMALE_VOICE_ID = (os.getenv("ELEVEN_DEFAULT_FEMALE_VOICE_ID") or "").strip()

# If True, pick a new random voice per SCENE (or per sentence-part in both+alternate_sentences).
# If False (default), pick one male voice + one female voice ONCE per run and reuse (recommended).
VOICE_RANDOMIZE_PER_SCENE_DEFAULT = (os.getenv("VOICE_RANDOMIZE_PER_SCENE", "false").lower() == "true")

# Optional: default voice settings (can be overridden per state)
DEFAULT_VOICE_SETTINGS = {
    "stability": float(os.getenv("ELEVEN_STABILITY", "0.5")),
    "similarity_boost": float(os.getenv("ELEVEN_SIMILARITY_BOOST", "0.75")),
    "style": float(os.getenv("ELEVEN_STYLE", "0.0")),
    "speed": float(os.getenv("ELEVEN_SPEED", "1.0")),
    "use_speaker_boost": (os.getenv("ELEVEN_USE_SPEAKER_BOOST", "true").lower() == "true"),
}

# --------------------------------------------
# Eleven v3 Audio Tags (emotion/direction etc.)
# v3 reads tags like [laughs], [whispers], [curious], [excited]
# --------------------------------------------

TAG_MAP = {
    "excitedly": "excited",
    "excited": "excited",
    "curiously": "curious",
    "curious": "curious",
    "sarcastically": "sarcastic",
    "sarcastic": "sarcastic",
    "mischievously": "mischievously",

    "dramatically": "excited",   # best-effort
    "dramatic": "excited",

    "whispering": "whispers",
    "whispers": "whispers",
    "whisper": "whispers",

    "giggling": "laughs",
    "giggles": "laughs",
    "laughing": "laughs",
    "laughs": "laughs",
    "chuckles": "chuckles",

    "with genuine belly laugh": "laughs harder",
    "belly laugh": "laughs harder",

    "sighs": "sighs",
    "sigh": "sighs",
    "exhales": "exhales",

    "crying": "crying",
    "sad": "sad",
    "angry": "angry",

    "happily": "happily",
    "delighted": "happily",
    "delightedly": "happily",
    "impressed": "excited",
}

# A conservative allowlist of tags that are typically safe.
# If a tag isn't in here, we will try to map it; otherwise we remove it
# so it doesn't get spoken literally.
KNOWN_V3_TAGS = {
    "laughs", "laughs harder", "starts laughing", "wheezing",
    "chuckles",
    "whispers", "shouts",
    "sighs", "exhales", "clears throat", "coughs", "gasps", "snorts",
    "sarcastic", "curious", "excited", "crying", "mischievously",
    "sad", "angry", "happily",
    "applause", "clapping", "gunshot", "explosion", "swallows", "gulps",
    "slowly", "quickly",
}

# --------------------------------------------
# Language map (UI label -> ISO 639-1 code)
# --------------------------------------------
LANGUAGE_MAP = {
    # English
    "english": "en",
    "en": "en",
    "en-in": "en",

    # India
    "hindi": "hi",
    "hi": "hi",
    "hi-in": "hi",

    "marathi": "mr",
    "mr": "mr",
    "mr-in": "mr",

    "bengali": "bn",
    "bangla": "bn",
    "bn": "bn",
    "bn-in": "bn",

    "tamil": "ta",
    "ta": "ta",
    "ta-in": "ta",

    "telugu": "te",
    "te": "te",
    "te-in": "te",

    "gujarati": "gu",
    "gu": "gu",
    "gu-in": "gu",

    "kannada": "kn",
    "kn": "kn",
    "kn-in": "kn",

    "malayalam": "ml",
    "ml": "ml",
    "ml-in": "ml",

    "punjabi": "pa",
    "pa": "pa",
    "pa-in": "pa",

    "odia": "or",
    "oriya": "or",
    "or": "or",
    "or-in": "or",

    "assamese": "as",
    "as": "as",
    "as-in": "as",

    "urdu": "ur",
    "ur": "ur",
    "ur-in": "ur",
}

def resolve_lang_code(x: str) -> str:
    if not x:
        return "en"
    s = str(x).strip().lower()
    s = s.replace("_", "-")  # hi_IN -> hi-in
    return LANGUAGE_MAP.get(s, s.split("-", 1)[0])

def normalize_lang(tts_lang: str) -> str:
    return resolve_lang_code(tts_lang)

def normalize_voice_mode(mode: Optional[str]) -> str:
    m = (mode or "female").strip().lower()
    if m not in {"male", "female", "both"}:
        return "female"
    return m

def normalize_both_mode(mode: Optional[str]) -> str:
    m = (mode or "alternate_scenes").strip().lower()
    if m not in {"alternate_scenes", "random_scenes", "alternate_sentences"}:
        return "alternate_scenes"
    return m

def _extract_json_object(text: str) -> str:
    """
    For cases where you saved JSON inside a .py file, or extra text exists.
    Extract first {...} block and return it.
    """
    if not isinstance(text, str):
        raise ValueError("voice pools content must be text")
    t = text.strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Could not find JSON object in voice pools file")
    return t[start:end+1]

def load_voice_pools(path: str = ELEVEN_VOICE_POOLS_PATH) -> Dict[str, Dict[str, List[str]]]:
    """
    Loads voice pools from JSON (or JSON embedded inside .py):
    {
      "hi": {"male": ["..."], "female": ["..."]},
      "ta": {"male": [...], "female": [...]}
    }
    """
    # If the requested path doesn't exist, try common alternatives
    if not os.path.exists(path):
        if os.path.exists("voice_pools.json"):
            path = "voice_pools.json"
        elif os.path.exists("voice_pools.py"):
            path = "voice_pools.py"
        else:
            return {}

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    # If it's a .py file or has extra stuff, extract JSON object
    if path.lower().endswith(".py"):
        raw = _extract_json_object(raw)

    data = json.loads(raw)

    def _clean_ids(ids: List[Any]) -> List[str]:
        out: List[str] = []
        seen = set()
        for x in (ids or []):
            s = str(x).strip()
            if not s:
                continue
            if s == "..." or s.lower() in {"null", "none"}:
                continue
            if "..." in s:
                continue
            if s not in seen:
                out.append(s)
                seen.add(s)
        return out

    pools: Dict[str, Dict[str, List[str]]] = {}
    for lang, gender_map in (data or {}).items():
        if not isinstance(gender_map, dict):
            continue
        lang_key = str(lang).lower().strip()
        pools[lang_key] = {
            "male": _clean_ids(gender_map.get("male") or []),
            "female": _clean_ids(gender_map.get("female") or []),
        }

    return pools

def pick_random_voice_id(pools: Dict[str, Dict[str, List[str]]], lang: str, gender: str, rng: random.Random) -> str:
    lang = normalize_lang(lang)
    gender = "male" if gender == "male" else "female"

    ids = (pools.get(lang, {}).get(gender) or [])
    if ids:
        return rng.choice(ids)

    # Fallbacks
    if gender == "male" and ELEVEN_DEFAULT_MALE_VOICE_ID:
        return ELEVEN_DEFAULT_MALE_VOICE_ID
    if gender == "female" and ELEVEN_DEFAULT_FEMALE_VOICE_ID:
        return ELEVEN_DEFAULT_FEMALE_VOICE_ID

    raise ValueError(
        f"No voice IDs configured for lang='{lang}', gender='{gender}'. "
        f"Add them to {ELEVEN_VOICE_POOLS_PATH} or set ELEVEN_DEFAULT_*_VOICE_ID."
    )

def split_into_sentences(text: str) -> List[str]:
    """
    Splits on common sentence punctuation including Indian danda (।).
    Keeps short segments; filters empties.
    """
    if not text:
        return []
    parts = re.split(r"(?<=[\.\!\?\u0964])\s+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]

def concat_mp3(files: List[str], out_path: str) -> None:
    """
    Concatenate mp3 files using ffmpeg concat demuxer.
    """
    if not files:
        raise ValueError("concat_mp3: empty file list")

    list_path = out_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            # ffmpeg concat works more reliably with forward slashes on Windows
            p_norm = p.replace("\\", "/")

            # escape single quotes inside the file path (rare, but safe)
            p_escaped = p_norm.replace("'", "'\\''")

            f.write(f"file '{p_escaped}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c", "copy",
        out_path
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    try:
        os.remove(list_path)
    except OSError:
        pass


def _normalize_tag_content(tag_content: str) -> str:
    t = (tag_content or "").strip().lower()
    t = re.sub(r"\s+", " ", t)

    # common patterns
    if "belly" in t and "laugh" in t:
        return "laughs harder"
    if "starts" in t and "laugh" in t:
        return "starts laughing"
    if "laugh" in t and t not in TAG_MAP:
        return "laughs"

    if t.startswith("with "):
        t = t[5:].strip()

    # map via TAG_MAP
    if t in TAG_MAP:
        return TAG_MAP[t]

    # strip trailing "ly" (excitedly -> excited)
    if t.endswith("ly") and len(t) > 4:
        t2 = t[:-2]
        if t2 in TAG_MAP:
            return TAG_MAP[t2]

    return t

def apply_v3_audio_tags(text: str) -> str:
    """
    Converts your script's [tone] tags into v3 audio tags.
    For unknown tags: we remove them to prevent literal speaking.
    """
    if not text:
        return text

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        norm = _normalize_tag_content(inner)

        # If recognized (known list or mapped), keep as tag; else REMOVE
        if norm in KNOWN_V3_TAGS:
            return f"[{norm}]"
        if norm in TAG_MAP.values():
            return f"[{norm}]"

        # If still not recognized, drop it
        return ""

    # Replace bracket tags
    out = re.sub(r"\[([^\]]+)\]", repl, text)

    # Clean extra whitespace left by tag removal
    out = re.sub(r"\s+", " ", out).strip()
    return out

def strip_bracket_tags(text: str) -> str:
    t = re.sub(r"\[[^\]]*\]", "", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t

def build_voice_settings(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build ElevenLabs voice_settings safely.
    IMPORTANT: Your pipeline uses state["style"] as a video-style STRING (e.g. "Cinematic").
    ElevenLabs voice_settings["style"] must be a FLOAT.
    So we only accept numeric values for the voice style.
    """
    vs = dict(DEFAULT_VOICE_SETTINGS)

    # Allow state override via voice_settings dict (preferred)
    if isinstance(state.get("voice_settings"), dict):
        for k, v in state["voice_settings"].items():
            vs[k] = v

    def _maybe_float(x):
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            try:
                return float(x.strip())
            except Exception:
                return None
        return None

    # Only apply top-level overrides if the types are correct
    if "stability" in state and state["stability"] is not None:
        v = _maybe_float(state["stability"])
        if v is not None:
            vs["stability"] = v

    if "similarity_boost" in state and state["similarity_boost"] is not None:
        v = _maybe_float(state["similarity_boost"])
        if v is not None:
            vs["similarity_boost"] = v

    # ⚠️ DO NOT blindly take state["style"] (that's your video style like "Cinematic")
    # Only accept a numeric voice style value if user provides it as voice_style or voice_settings["style"]
    if "voice_style" in state and state["voice_style"] is not None:
        v = _maybe_float(state["voice_style"])
        if v is not None:
            vs["style"] = v

    if "speed" in state and state["speed"] is not None:
        v = _maybe_float(state["speed"])
        if v is not None:
            vs["speed"] = v

    if "use_speaker_boost" in state and state["use_speaker_boost"] is not None:
        vs["use_speaker_boost"] = bool(state["use_speaker_boost"])

    return vs


def ensure_both_appear(assignments: List[str]) -> List[str]:
    """
    Ensures random_scenes uses at least one male and one female when there are >=2 scenes.
    """
    if len(assignments) < 2:
        return assignments
    if "male" not in assignments:
        assignments[0] = "male"
    if "female" not in assignments:
        assignments[1] = "female"
    return assignments

def _safe_tts_convert(client, **kwargs):
    """
    ElevenLabs SDK signature differs across versions.
    Try the most complete call; if it TypeErrors, retry by dropping optional args.
    """
    # Attempt 1: full kwargs
    try:
        return client.text_to_speech.convert(**kwargs)
    except TypeError:
        pass

    # Attempt 2: drop language_code if present
    kwargs2 = dict(kwargs)
    kwargs2.pop("language_code", None)
    try:
        return client.text_to_speech.convert(**kwargs2)
    except TypeError:
        pass

    # Attempt 3: drop voice_settings too
    kwargs3 = dict(kwargs2)
    kwargs3.pop("voice_settings", None)
    return client.text_to_speech.convert(**kwargs3)

def generate_voice(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    state inputs expected:
      - voice_overs: List[str]
      - tts_lang: str (e.g., "hi" or "hi-in" or "Hindi")
      - voice_mode: "male"|"female"|"both"  (optional)
      - both_mode: "alternate_scenes"|"random_scenes"|"alternate_sentences" (optional)
      - seed: int (optional)
      - model_id: override model (optional)
      - output_format: override output format (optional)
      - voice_settings: dict override settings (optional)
      - voice_randomize_per_scene: bool (optional)
    """
    if not ELEVEN_API_KEY:
        raise ValueError("Missing ELEVEN_API_KEY in environment.")

    voice_overs: List[str] = state.get("voice_overs") or []
    if not voice_overs:
        raise ValueError("voice_overs missing/empty in state.")

    # Import with compatibility across SDK versions
    try:
        from elevenlabs.client import ElevenLabs
    except Exception:
        from elevenlabs import ElevenLabs

    client = ElevenLabs(api_key=ELEVEN_API_KEY)

    lang = normalize_lang(state.get("tts_lang", "en"))
    voice_mode = normalize_voice_mode(state.get("voice_mode"))
    both_mode = normalize_both_mode(state.get("both_mode"))
    rng = random.Random(state.get("seed"))

    pools = load_voice_pools()
    model_id = (state.get("model_id") or ELEVEN_MODEL_ID).strip()
    output_format = (state.get("output_format") or ELEVEN_OUTPUT_FORMAT).strip()
    voice_settings = build_voice_settings(state)
    randomize_per_scene = bool(state.get("voice_randomize_per_scene", VOICE_RANDOMIZE_PER_SCENE_DEFAULT))

    output_dir = "voice_outputs"
    os.makedirs(output_dir, exist_ok=True)
    audio_files: List[str] = []

    # If "both" requested but only 1 scene, guarantee both speak by forcing alternate_sentences
    if voice_mode == "both" and len(voice_overs) < 2 and both_mode in {"alternate_scenes", "random_scenes"}:
        both_mode = "alternate_sentences"

    # Decide speaker gender per scene (for scene-level modes)
    if voice_mode in {"male", "female"}:
        gender_per_scene = [voice_mode] * len(voice_overs)
    else:
        if both_mode == "alternate_scenes":
            gender_per_scene = ["male" if (i % 2 == 0) else "female" for i in range(len(voice_overs))]
        elif both_mode == "random_scenes":
            gender_per_scene = [rng.choice(["male", "female"]) for _ in range(len(voice_overs))]
            gender_per_scene = ensure_both_appear(gender_per_scene)
        else:
            gender_per_scene = ["both"] * len(voice_overs)

    # Pick one male/female voice for the whole run (recommended), unless randomize_per_scene=True
    fixed_male_voice_id = pick_random_voice_id(pools, lang, "male", rng)
    fixed_female_voice_id = pick_random_voice_id(pools, lang, "female", rng)

    # Optional language_code hint (only if 2 letters)
    language_code = lang if isinstance(lang, str) and len(lang) == 2 else None

    for idx, raw_text in enumerate(voice_overs, start=1):
        out_path = os.path.join(output_dir, f"scene{idx}.mp3")

        # Prepare text
        if model_id == "eleven_v3":
            text = apply_v3_audio_tags(raw_text)
        else:
            text = strip_bracket_tags(raw_text)

        # Scene-level modes (male-only / female-only / both with per-scene gender)
        if voice_mode != "both" or both_mode in {"alternate_scenes", "random_scenes"}:
            gender = gender_per_scene[idx - 1] if gender_per_scene else "female"

            if randomize_per_scene:
                voice_id = pick_random_voice_id(pools, lang, gender, rng)
            else:
                voice_id = fixed_male_voice_id if gender == "male" else fixed_female_voice_id

            audio = _safe_tts_convert(
                client,
                voice_id=voice_id,
                model_id=model_id,
                text=text,
                output_format=output_format,
                voice_settings=voice_settings,
                language_code=language_code,
            )

            with open(out_path, "wb") as f:
                if isinstance(audio, (bytes, bytearray)):
                    f.write(audio)
                else:
                    for chunk in audio:
                        if chunk:
                            f.write(chunk)

            audio_files.append(out_path)
            continue

        # BOTH + alternate_sentences: split and alternate male/female inside each scene, then concat
        parts = split_into_sentences(text)
        if not parts:
            parts = [text]

        tmp_files: List[str] = []
        for p_i, part in enumerate(parts):
            gender = "male" if (p_i % 2 == 0) else "female"

            if randomize_per_scene:
                voice_id = pick_random_voice_id(pools, lang, gender, rng)
            else:
                voice_id = fixed_male_voice_id if gender == "male" else fixed_female_voice_id

            tmp_path = os.path.join(output_dir, f"scene{idx}_part{p_i+1}.mp3")
            audio = _safe_tts_convert(
                client,
                voice_id=voice_id,
                model_id=model_id,
                text=part,
                output_format=output_format,
                voice_settings=voice_settings,
                language_code=language_code,
            )

            with open(tmp_path, "wb") as f:
                if isinstance(audio, (bytes, bytearray)):
                    f.write(audio)
                else:
                    for chunk in audio:
                        if chunk:
                            f.write(chunk)

            tmp_files.append(tmp_path)

        if len(tmp_files) == 1:
            os.replace(tmp_files[0], out_path)
        else:
            concat_mp3(tmp_files, out_path)
            for p in tmp_files:
                try:
                    os.remove(p)
                except OSError:
                    pass

        audio_files.append(out_path)

    state["audio_files"] = audio_files
    return state
