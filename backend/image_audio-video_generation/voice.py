# voice.py
import os
import json
import re
import random
import subprocess
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
load_dotenv()

ELEVEN_API_KEY = (os.getenv("ELEVEN_API_KEY") or "").strip().strip('"').strip("'")
ELEVEN_OUTPUT_FORMAT = (os.getenv("ELEVEN_OUTPUT_FORMAT") or "mp3_44100_128").strip()
ELEVEN_MODEL_ID = (os.getenv("ELEVEN_MODEL_ID") or "eleven_v3").strip()

ELEVEN_VOICE_POOLS_PATH = (os.getenv("ELEVEN_VOICE_POOLS_PATH") or "voice_pools.json").strip()

ELEVEN_DEFAULT_MALE_VOICE_ID = (os.getenv("ELEVEN_DEFAULT_MALE_VOICE_ID") or "").strip()
ELEVEN_DEFAULT_FEMALE_VOICE_ID = (os.getenv("ELEVEN_DEFAULT_FEMALE_VOICE_ID") or "").strip()

VOICE_RANDOMIZE_PER_SCENE_DEFAULT = (os.getenv("VOICE_RANDOMIZE_PER_SCENE", "false").lower() == "true")

DEFAULT_VOICE_SETTINGS = {
    "stability": float(os.getenv("ELEVEN_STABILITY", "0.5")),
    "similarity_boost": float(os.getenv("ELEVEN_SIMILARITY_BOOST", "0.75")),
    "style": float(os.getenv("ELEVEN_STYLE", "0.0")),
    "speed": float(os.getenv("ELEVEN_SPEED", "1.0")),
    "use_speaker_boost": (os.getenv("ELEVEN_USE_SPEAKER_BOOST", "true").lower() == "true"),
}

TAG_MAP = {
    "excitedly": "excited",
    "excited": "excited",
    "curiously": "curious",
    "curious": "curious",
    "sarcastically": "sarcastic",
    "sarcastic": "sarcastic",
    "dramatically": "excited",
    "whispering": "whispers",
    "whispers": "whispers",
    "giggling": "laughs",
    "giggles": "laughs",
    "laughing": "laughs",
    "laughs": "laughs",
    "chuckles": "chuckles",
    "sighs": "sighs",
    "crying": "crying",
    "sad": "sad",
    "angry": "angry",
    "delighted": "happily",
    "happily": "happily",
    "impressed": "excited",
    "with genuine belly laugh": "laughs harder",
    "belly laugh": "laughs harder",
}

KNOWN_V3_TAGS = {
    "laughs", "laughs harder", "starts laughing", "wheezing",
    "chuckles",
    "whispers", "shouts",
    "sighs", "exhales", "clears throat", "coughs", "gasps", "snorts",
    "sarcastic", "curious", "excited", "crying", "mischievously",
    "sad", "angry", "happily",
    "applause", "clapping",
    "slowly", "quickly",
}

LANGUAGE_MAP = {
    "english": "en", "en": "en", "en-in": "en",
    "hindi": "hi", "hi": "hi", "hi-in": "hi",
    "marathi": "mr", "mr": "mr", "mr-in": "mr",
    "bengali": "bn", "bangla": "bn", "bn": "bn", "bn-in": "bn",
    "tamil": "ta", "ta": "ta", "ta-in": "ta",
    "telugu": "te", "te": "te", "te-in": "te",
    "gujarati": "gu", "gu": "gu", "gu-in": "gu",
    "kannada": "kn", "kn": "kn", "kn-in": "kn",
    "malayalam": "ml", "ml": "ml", "ml-in": "ml",
    "punjabi": "pa", "pa": "pa", "pa-in": "pa",
    "odia": "or", "oriya": "or", "or": "or", "or-in": "or",
    "assamese": "as", "as": "as", "as-in": "as",
    "urdu": "ur", "ur": "ur", "ur-in": "ur",
}

def normalize_lang(x: str) -> str:
    if not x:
        return "en"
    s = str(x).strip().lower().replace("_", "-")
    return LANGUAGE_MAP.get(s, s.split("-", 1)[0])

def normalize_voice_mode(mode: Optional[str]) -> str:
    m = (mode or "female").strip().lower()
    return m if m in {"male", "female", "both"} else "female"

def normalize_both_mode(mode: Optional[str]) -> str:
    m = (mode or "alternate_scenes").strip().lower()
    return m if m in {"alternate_scenes", "random_scenes", "alternate_sentences"} else "alternate_scenes"

def _extract_json_object(text: str) -> str:
    t = text.strip()
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Could not find JSON object in voice pools file")
    return t[start:end+1]

def load_voice_pools(path: str = ELEVEN_VOICE_POOLS_PATH) -> Dict[str, Dict[str, List[str]]]:
    if not os.path.exists(path):
        if os.path.exists("voice_pools.json"):
            path = "voice_pools.json"
        elif os.path.exists("voice_pools.py"):
            path = "voice_pools.py"
        else:
            return {}

    raw = open(path, "r", encoding="utf-8").read()
    if path.lower().endswith(".py"):
        raw = _extract_json_object(raw)
    data = json.loads(raw)

    def clean_ids(ids: List[Any]) -> List[str]:
        out, seen = [], set()
        for x in ids or []:
            s = str(x).strip()
            if not s or s == "..." or "..." in s or s.lower() in {"none", "null"}:
                continue
            if s not in seen:
                out.append(s); seen.add(s)
        return out

    pools: Dict[str, Dict[str, List[str]]] = {}
    for lang, gm in (data or {}).items():
        if not isinstance(gm, dict): 
            continue
        pools[str(lang).lower().strip()] = {
            "male": clean_ids(gm.get("male") or []),
            "female": clean_ids(gm.get("female") or []),
        }
    return pools

def pick_random_voice_id(pools: Dict[str, Dict[str, List[str]]], lang: str, gender: str, rng: random.Random) -> str:
    lang = normalize_lang(lang)
    gender = "male" if gender == "male" else "female"
    ids = pools.get(lang, {}).get(gender, []) or []
    if ids:
        return rng.choice(ids)

    if gender == "male" and ELEVEN_DEFAULT_MALE_VOICE_ID:
        return ELEVEN_DEFAULT_MALE_VOICE_ID
    if gender == "female" and ELEVEN_DEFAULT_FEMALE_VOICE_ID:
        return ELEVEN_DEFAULT_FEMALE_VOICE_ID

    raise ValueError(f"No voice IDs configured for lang='{lang}', gender='{gender}'.")

def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float((r.stdout or "").strip() or "0")

def concat_mp3(files: List[str], out_path: str) -> None:
    if not files:
        raise ValueError("concat_mp3: empty file list")
    list_path = out_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in files:
            p_norm = p.replace("\\", "/")
            p_escaped = p_norm.replace("'", "'\\''")
            f.write(f"file '{p_escaped}'\n")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", out_path],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    try: os.remove(list_path)
    except OSError: pass

def split_into_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[\.\!\?\u0964])\s+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]

def _normalize_tag_content(tag_content: str) -> str:
    t = re.sub(r"\s+", " ", (tag_content or "").strip().lower())
    if "belly" in t and "laugh" in t:
        return "laughs harder"
    if t.startswith("with "):
        t = t[5:].strip()
    if t in TAG_MAP:
        return TAG_MAP[t]
    if t.endswith("ly") and len(t) > 4 and t[:-2] in TAG_MAP:
        return TAG_MAP[t[:-2]]
    return t

def apply_v3_audio_tags(text: str) -> str:
    if not text:
        return text

    def repl(m: re.Match) -> str:
        inner = m.group(1)
        norm = _normalize_tag_content(inner)
        if norm in KNOWN_V3_TAGS or norm in TAG_MAP.values():
            return f"[{norm}]"
        return ""  # drop unknown tags to avoid speaking them

    out = re.sub(r"\[([^\]]+)\]", repl, text)
    out = re.sub(r"\s+", " ", out).strip()
    return out

def strip_bracket_tags(text: str) -> str:
    t = re.sub(r"\[[^\]]*\]", "", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    return t

def build_voice_settings(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    IMPORTANT:
    - state["style"] is VIDEO style string like "Cinematic"
    - Eleven voice_settings["style"] must be float
    So: only accept numeric overrides from voice_settings or voice_style
    """
    vs = dict(DEFAULT_VOICE_SETTINGS)

    if isinstance(state.get("voice_settings"), dict):
        for k, v in state["voice_settings"].items():
            vs[k] = v

    def maybe_float(x):
        if isinstance(x, (int, float)):
            return float(x)
        if isinstance(x, str):
            try: return float(x.strip())
            except Exception: return None
        return None

    for k in ("stability", "similarity_boost", "speed"):
        if k in state and state[k] is not None:
            v = maybe_float(state[k])
            if v is not None:
                vs[k] = v

    if "voice_style" in state and state["voice_style"] is not None:
        v = maybe_float(state["voice_style"])
        if v is not None:
            vs["style"] = v

    if "use_speaker_boost" in state and state["use_speaker_boost"] is not None:
        vs["use_speaker_boost"] = bool(state["use_speaker_boost"])

    return vs

def ensure_both_appear(assignments: List[str]) -> List[str]:
    if len(assignments) < 2:
        return assignments
    if "male" not in assignments:
        assignments[0] = "male"
    if "female" not in assignments:
        assignments[1] = "female"
    return assignments

def _safe_tts_convert(client, **kwargs):
    try:
        return client.text_to_speech.convert(**kwargs)
    except TypeError:
        k2 = dict(kwargs); k2.pop("language_code", None)
        try:
            return client.text_to_speech.convert(**k2)
        except TypeError:
            k3 = dict(k2); k3.pop("voice_settings", None)
            return client.text_to_speech.convert(**k3)

def generate_voice(state: Dict[str, Any]) -> Dict[str, Any]:
    if not ELEVEN_API_KEY:
        raise ValueError("Missing ELEVEN_API_KEY in environment.")
    voice_overs: List[str] = state.get("voice_overs") or []
    if not voice_overs:
        raise ValueError("voice_overs missing/empty in state.")

    # SDK import compatibility
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
    language_code = lang if isinstance(lang, str) and len(lang) == 2 else None

    output_dir = "voice_outputs"
    os.makedirs(output_dir, exist_ok=True)

    # GENDER ASSIGNMENT (strict alternation for alternate_scenes)
    if voice_mode in {"male", "female"}:
        gender_per_scene = [voice_mode] * len(voice_overs)
    else:
        if both_mode == "alternate_scenes":
            gender_per_scene = ["male" if (i % 2 == 0) else "female" for i in range(len(voice_overs))]
        elif both_mode == "random_scenes":
            gender_per_scene = ensure_both_appear([rng.choice(["male", "female"]) for _ in range(len(voice_overs))])
        else:
            gender_per_scene = ["both"] * len(voice_overs)

    # Pick fixed voices for continuity unless randomize_per_scene=True
    fixed_male_voice_id = pick_random_voice_id(pools, lang, "male", rng)
    fixed_female_voice_id = pick_random_voice_id(pools, lang, "female", rng)

    audio_files: List[str] = []
    audio_durations: List[float] = []

    for idx, raw_text in enumerate(voice_overs, start=1):
        out_path = os.path.join(output_dir, f"scene{idx}.mp3")

        # text prep
        if model_id == "eleven_v3":
            text = apply_v3_audio_tags(raw_text)
        else:
            text = strip_bracket_tags(raw_text)

        # STANDARD BOTH (alternate_scenes / random_scenes) => exactly 1 audio per voiceover
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
            audio_durations.append(get_audio_duration(out_path))
            continue

        # BOTH + alternate_sentences (used only if you explicitly set it)
        parts = split_into_sentences(text) or [text]
        tmp_files: List[str] = []
        for p_i, part in enumerate(parts):
            gender = "male" if (p_i % 2 == 0) else "female"
            voice_id = (pick_random_voice_id(pools, lang, gender, rng) if randomize_per_scene
                        else (fixed_male_voice_id if gender == "male" else fixed_female_voice_id))

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
                try: os.remove(p)
                except OSError: pass

        audio_files.append(out_path)
        audio_durations.append(get_audio_duration(out_path))

    state["audio_files"] = audio_files
    state["audio_durations"] = audio_durations
    state["audio_total_duration"] = float(sum(audio_durations))
    state["speaker_genders"] = gender_per_scene
    return state
