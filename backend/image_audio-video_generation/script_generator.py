# script_generator.py
import os
import re
import json
from typing import Any, Dict

from dotenv import load_dotenv
from langchain_core.prompts import PromptTemplate
from openai import OpenAI

load_dotenv()


def sanitize_model_json(text: str) -> str:
    if not isinstance(text, str):
        return text
    t = text.strip()
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t).strip()
    start = t.find("{"); end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start:end+1]
    return t


def _get_openrouter_key() -> str:
    k = (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")
    if not k:
        raise ValueError("OPENROUTER_API_KEY missing/empty.")
    return k


def generate_script(state: Dict[str, Any]) -> Dict[str, Any]:
    duration_seconds = state.get("duration_seconds", 30)
    try:
        duration_seconds = int(float(duration_seconds))
    except Exception:
        duration_seconds = 30
    if duration_seconds <= 0:
        duration_seconds = 30

    prev_audio = state.get("previous_audio_total_duration")
    attempt = int(state.get("duration_attempt", 0) or 0)

    feedback = ""
    if prev_audio is not None:
        try:
            prev_audio_f = float(prev_audio)
            delta = duration_seconds - prev_audio_f
            if abs(delta) > 0.5:
                if delta > 0:
                    feedback = f"\nIMPORTANT FEEDBACK: Last attempt spoken audio was ~{prev_audio_f:.1f}s, but target is {duration_seconds}s. EXPAND the spoken content by ~{delta:.1f}s.\n"
                else:
                    feedback = f"\nIMPORTANT FEEDBACK: Last attempt spoken audio was ~{prev_audio_f:.1f}s, but target is {duration_seconds}s. SHORTEN the spoken content by ~{abs(delta):.1f}s.\n"
        except Exception:
            pass

    prompt_string = f"""
You are an expert political content creator and video editor. Generate a script for a faceless vertical video (9:16).

TARGET:
- Total spoken duration must be about {duration_seconds} seconds.
- You MUST set expected_time_in_seconds as INTEGERS so that the SUM across scenes is EXACTLY {duration_seconds}.

PACING RULE:
- Assume normal speaking pace ~2.2 words/sec (space-delimited words in the target script).
- Make each scene's "voiceover" length match its expected_time_in_seconds.
{feedback}

Instructions:
- Split into scenes
- Hook in first 3 seconds
- End with CTA
- Add tone tags in [] (e.g. [excited], [curious], [laughs]) — these will drive TTS expression
- IMPORTANT: Write ALL voiceover strictly in {", ".join(state.get("languages", []))}. No English except proper nouns.
- Target language code: {state.get("tts_lang","en")} and use native script only.

Output STRICT JSON:
{{
  "metadata": {{
    "topic": "<topic_name>",
    "language": "{", ".join(state.get("languages", []))}",
    "style": "{state.get("style","")}",
    "target_duration_seconds": {duration_seconds},
    "attempt": {attempt}
  }},
  "video_script": [
    {{
      "scene_id": 1,
      "expected_time_in_seconds": 6,
      "voiceover": "....",
      "visual_keywords": "k1, k2, k3",
      "overlay_text": "TEXT"
    }}
  ]
}}
Query:
{state["user_query"]}
"""

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=_get_openrouter_key())
    resp = client.chat.completions.create(
        model="nvidia/nemotron-3-nano-30b-a3b:free",
        messages=[
            {"role": "system", "content": "Return valid JSON only."},
            {"role": "user", "content": prompt_string},
        ],
    )
    script = sanitize_model_json(resp.choices[0].message.content)
    return {"video_script": script}


def extract_script(state: Dict[str, Any]) -> Dict[str, Any]:
    clean = sanitize_model_json(state["video_script"])
    script_data = json.loads(clean)

    voice_overs = []
    for scene in script_data.get("video_script", []):
        vo = scene.get("voiceover", "")
        if vo:
            voice_overs.append(vo)

    print(f"Extracted {len(voice_overs)} voiceovers")
    return {"voice_overs": voice_overs}
