# workflow_app.py
# Orchestrates the full LangGraph pipeline using:
# - script_generator.py (generate_script, extract_script)
# - voice.py           (generate_voice)
# - images.py          (generate_image)
# - video.py           (build_scenes, stitch_final_video)

from __future__ import annotations

import os
import shutil
from typing import Any, Dict, List, TypedDict, Optional

from langgraph.graph import START, END, StateGraph

from script_generator import generate_script, extract_script
from voice import generate_voice
from images import generate_image
from video import build_scenes, stitch_final_video


class VideoState(TypedDict, total=False):
    # Inputs
    user_query: str
    languages: List[str]
    style: str
    tts_lang: str

    # Voice controls
    voice_mode: str                 # "male" | "female" | "both"
    both_mode: str                  # "alternate_scenes" | "random_scenes" | "alternate_sentences"
    voice_randomize_per_scene: bool
    seed: int

    # Intermediate
    video_script: Any
    voice_overs: List[str]
    audio_files: List[str]
    image_files: List[str]

    # Video assembly
    scene_videos: List[str]
    scene_durations: List[float]
    all_word_segments: List[List[dict]]

    # Output
    output_file: str
    final_video_path: str


# ----------------------------
# Safety checks (no surprises)
# ----------------------------
def _require_bin(name: str) -> None:
    if shutil.which(name) is None:
        raise EnvironmentError(
            f"Required binary '{name}' not found on PATH. "
            f"Install it and ensure it is available in your terminal."
        )

def _validate_runtime(inputs: Dict[str, Any]) -> None:
    # ffmpeg tooling
    _require_bin("ffmpeg")
    _require_bin("ffprobe")

    # Required user inputs
    if not (inputs.get("user_query") or "").strip():
        raise ValueError("Missing required input: user_query")
    if not inputs.get("tts_lang"):
        raise ValueError("Missing required input: tts_lang")
    if not inputs.get("languages"):
        raise ValueError("Missing required input: languages")
    if not inputs.get("style"):
        raise ValueError("Missing required input: style")

    # Required API keys
    # Script + images use OpenRouter (per your existing pipeline)
    if not (os.getenv("OPENROUTER_API_KEY") or "").strip():
        raise ValueError("Missing OPENROUTER_API_KEY (required for script + image generation).")
    # Voice uses ElevenLabs
    if not (os.getenv("ELEVEN_API_KEY") or "").strip():
        raise ValueError("Missing ELEVEN_API_KEY (required for voice generation).")


# ----------------------------
# LangGraph node wrappers
# (Return ONLY state updates)
# ----------------------------
def node_generate_script(state: VideoState) -> Dict[str, Any]:
    return generate_script(dict(state))

def node_extract_script(state: VideoState) -> Dict[str, Any]:
    return extract_script(dict(state))

def node_generate_assets(state: VideoState) -> Dict[str, Any]:
    # Voice
    s_voice = dict(state)
    voice_out = generate_voice(s_voice)
    audio_files = voice_out.get("audio_files")

    # Images
    s_img = dict(state)
    img_out = generate_image(s_img)
    image_files = img_out.get("image_files")

    updates: Dict[str, Any] = {}
    if audio_files is not None:
        updates["audio_files"] = audio_files
    if image_files is not None:
        updates["image_files"] = image_files
    return updates

def node_build_scenes(state: VideoState) -> Dict[str, Any]:
    out = build_scenes(dict(state))
    return {
        "scene_videos": out.get("scene_videos", []),
        "scene_durations": out.get("scene_durations", []),
        "all_word_segments": out.get("all_word_segments", []),
    }

def node_stitch_final_video(state: VideoState) -> Dict[str, Any]:
    output_file = (state.get("output_file") or "final_video.mp4")
    stitch_final_video(dict(state), output_file=output_file)
    return {"final_video_path": output_file}


# ----------------------------
# Build workflow
# ----------------------------
def build_app():
    wf = StateGraph(VideoState)

    wf.add_node("generate_script", node_generate_script)
    wf.add_node("extract_script", node_extract_script)
    wf.add_node("generate_assets", node_generate_assets)
    wf.add_node("build_scenes", node_build_scenes)
    wf.add_node("stitch_final_video", node_stitch_final_video)

    wf.add_edge(START, "generate_script")
    wf.add_edge("generate_script", "extract_script")
    wf.add_edge("extract_script", "generate_assets")
    wf.add_edge("generate_assets", "build_scenes")
    wf.add_edge("build_scenes", "stitch_final_video")
    wf.add_edge("stitch_final_video", END)

    return wf.compile()


app = build_app()


# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    inputs: Dict[str, Any] = {
        "user_query": "Generate a video on Nationalism in 30 seconds only, in hindi language.",
        "languages": ["Hindi"],
        "style": "Cinematic",
        "tts_lang": "hi",

        # Voice options (optional)
        "voice_mode": "female",                 # "male" | "female" | "both"
        "both_mode": "alternate_scenes",      # or "alternate_sentences" / "random_scenes"
        "voice_randomize_per_scene": False,
        "seed": 42,

        # Output filename (optional)
        "output_file": "final_video.mp4",
    }

    _validate_runtime(inputs)

    final_state = app.invoke(inputs)

    print("\n✅ DONE")
    print("Final video path:", final_state.get("final_video_path"))
    print("Audio files:", final_state.get("audio_files"))
    print("Image files:", final_state.get("image_files"))
    print("Scene videos:", final_state.get("scene_videos"))
