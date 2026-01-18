# workflow_app.py
from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, TypedDict

from langgraph.graph import START, END, StateGraph

from script_generator import generate_script, extract_script
from voice import generate_voice
from images import generate_image
from video import build_scenes, stitch_final_video
from template import apply_template_from_state, SUPPORTED_TEMPLATES


class VideoState(TypedDict, total=False):
    # Inputs
    user_query: str
    languages: List[str]
    style: str
    tts_lang: str
    duration_seconds: int

    # Template inputs
    template_id: str               # t1..t7 or t9
    gameplay_video_path: str       # downloaded youtube gameplay path
    output_file: str               # final output path

    # Voice controls
    voice_mode: str
    both_mode: str
    voice_randomize_per_scene: bool
    seed: int

    # Duration retry
    duration_attempt: int
    max_duration_attempts: int
    previous_audio_total_duration: float
    duration_retry: bool

    # Intermediate
    video_script: Any
    voice_overs: List[str]
    audio_files: List[str]
    audio_durations: List[float]
    audio_total_duration: float

    image_files: List[str]

    scene_videos: List[str]
    scene_durations: List[float]
    all_word_segments: List[List[dict]]

    # Intermediate AI video (pre-template)
    ai_video_path: str

    # Output
    final_video_path: str


def _require_bin(name: str) -> None:
    if shutil.which(name) is None:
        raise EnvironmentError(f"Required binary '{name}' not found on PATH.")


def _validate_runtime(inputs: Dict[str, Any]) -> None:
    _require_bin("ffmpeg")
    _require_bin("ffprobe")

    if not (inputs.get("user_query") or "").strip():
        raise ValueError("Missing user_query")
    if not inputs.get("tts_lang"):
        raise ValueError("Missing tts_lang")
    if not inputs.get("languages"):
        raise ValueError("Missing languages")
    if not inputs.get("style"):
        raise ValueError("Missing style")
    if inputs.get("duration_seconds") is None:
        raise ValueError("Missing duration_seconds")
    d = int(float(inputs["duration_seconds"]))
    if d <= 0:
        raise ValueError("duration_seconds must be > 0")

    # Template fields
    tid = str(inputs.get("template_id") or "").strip()
    if tid not in SUPPORTED_TEMPLATES:
        raise ValueError(f"Invalid template_id='{tid}'. Supported: {list(SUPPORTED_TEMPLATES.keys())}")

    gp = str(inputs.get("gameplay_video_path") or "").strip()
    if not gp:
        raise ValueError("Missing gameplay_video_path")
    if not os.path.exists(gp):
        raise ValueError(f"gameplay_video_path does not exist: {gp}")

    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        raise ValueError("Missing OPENROUTER_API_KEY (script + images).")
    if not (os.getenv("ELEVEN_API_KEY") or "").strip():
        raise ValueError("Missing ELEVEN_API_KEY (voice).")


# ----------------------------
# Nodes
# ----------------------------
def node_generate_script(state: VideoState) -> Dict[str, Any]:
    return generate_script(dict(state))

def node_extract_script(state: VideoState) -> Dict[str, Any]:
    return extract_script(dict(state))

def node_generate_voice(state: VideoState) -> Dict[str, Any]:
    out = generate_voice(dict(state))
    return {
        "audio_files": out.get("audio_files", []),
        "audio_durations": out.get("audio_durations", []),
        "audio_total_duration": out.get("audio_total_duration", 0.0),
        "speaker_genders": out.get("speaker_genders", []),
    }

def node_check_duration(state: VideoState) -> Dict[str, Any]:
    target = float(state.get("duration_seconds") or 0)
    actual = float(state.get("audio_total_duration") or 0.0)

    tol = max(1.5, target * 0.08)

    attempt = int(state.get("duration_attempt") or 0)
    max_attempts = int(state.get("max_duration_attempts") or 2)

    ok = abs(actual - target) <= tol
    if ok:
        print(f"✅ Duration OK: audio={actual:.2f}s target={target:.2f}s tol={tol:.2f}s")
        return {"duration_retry": False}

    if attempt >= max_attempts:
        print(f"⚠️ Duration not matched after attempts. audio={actual:.2f}s target={target:.2f}s. Proceeding anyway.")
        return {"duration_retry": False}

    print(f"🔁 Duration mismatch: audio={actual:.2f}s target={target:.2f}s -> retry script (attempt {attempt+1}/{max_attempts})")
    return {
        "duration_retry": True,
        "duration_attempt": attempt + 1,
        "previous_audio_total_duration": actual,
    }

def route_after_check(state: VideoState) -> str:
    if state.get("duration_retry"):
        return "retry"
    # if not retry, branch on template
    tid = str(state.get("template_id") or "").strip()
    if tid == "t9":
        return "t9"
    return "standard"

def node_generate_image(state: VideoState) -> Dict[str, Any]:
    out = generate_image(dict(state))
    return {"image_files": out.get("image_files", [])}

def node_build_scenes(state: VideoState) -> Dict[str, Any]:
    out = build_scenes(dict(state))
    return {
        "scene_videos": out.get("scene_videos", []),
        "scene_durations": out.get("scene_durations", []),
        "all_word_segments": out.get("all_word_segments", []),
    }

def node_stitch_ai_video(state: VideoState) -> Dict[str, Any]:
    # Intermediate AI video (with subtitles already burned)
    ai_out = "ai_video_with_subs.mp4"
    stitch_final_video(dict(state), output_file=ai_out)
    return {"ai_video_path": ai_out}

def node_apply_template(state: VideoState) -> Dict[str, Any]:
    return apply_template_from_state(dict(state))


# ----------------------------
# Graph
# ----------------------------
def build_app():
    wf = StateGraph(VideoState)

    wf.add_node("generate_script", node_generate_script)
    wf.add_node("extract_script", node_extract_script)
    wf.add_node("generate_voice", node_generate_voice)
    wf.add_node("check_duration", node_check_duration)

    wf.add_node("generate_image", node_generate_image)
    wf.add_node("build_scenes", node_build_scenes)
    wf.add_node("stitch_ai_video", node_stitch_ai_video)
    wf.add_node("apply_template", node_apply_template)

    wf.add_edge(START, "generate_script")
    wf.add_edge("generate_script", "extract_script")
    wf.add_edge("extract_script", "generate_voice")
    wf.add_edge("generate_voice", "check_duration")

    wf.add_conditional_edges(
        "check_duration",
        route_after_check,
        {
            "retry": "generate_script",
            "t9": "apply_template",         # template 9: gameplay + audio + subs only
            "standard": "generate_image",   # templates 1..7: need AI video first
        }
    )

    wf.add_edge("generate_image", "build_scenes")
    wf.add_edge("build_scenes", "stitch_ai_video")
    wf.add_edge("stitch_ai_video", "apply_template")
    wf.add_edge("apply_template", END)

    return wf.compile()


app = build_app()


if __name__ == "__main__":
    inputs: Dict[str, Any] = {
        "user_query": "One piece anime in 30 seconds",
        "languages": ["English"],
        "style": "Cinematic",
        "tts_lang": "en",
        "duration_seconds": 30,

        # Template selection
        "template_id": "t9",  # t1..t7 or t9
        "gameplay_video_path": r"minecraft_gameplay.mp4",
        "output_file": r"final_templated_video.mp4",

        # Voice settings
        "voice_mode": "female",
        "both_mode": "alternate_scenes",
        "voice_randomize_per_scene": False,
        "seed": 42,

        "duration_attempt": 0,
        "max_duration_attempts": 2,

        # Optional template encoding params
        # "template_crf": 20,
        # "template_preset": "veryfast",
        # "template_ai_fit": "cover",
        # "template_gp_fit": "cover",
    }

    _validate_runtime(inputs)
    final_state = app.invoke(inputs)
    print("\n✅ DONE")
    print("Final:", final_state.get("final_video_path"))
