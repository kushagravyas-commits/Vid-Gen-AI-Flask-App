# video.py
import os
import subprocess
import random
from typing import Any, Dict, List, Optional, Tuple

from subtitles import normalize_whisper_lang, get_whisper_subtitles, generate_combined_ass_subtitles

# ============================================
# ANIMATION CONSTANTS (EXACT from images_to_video.py)
# ============================================
FPS = 60
WIDTH = 1080
HEIGHT = 1920
TRANSITION_DURATION = 1.0
MAX_ZOOM = 1.08
ZOOM_SPEED = 0.7


def get_audio_duration(audio_path: str) -> float:
    """Get audio duration using ffprobe"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return float((result.stdout or "").strip() or "0")


# ============================================
# ANIMATION-INTEGRATED SCENE BUILDING
# (Exact zoom logic from your monolith)
# ============================================
def combine_scene_with_animation(
    image_path: str,
    audio_path: str,
    output_path: str,
    scene_idx: int,
    is_extended: bool = False,
    tts_lang: Optional[str] = None,
    expected_text: Optional[str] = None,
) -> Tuple[float, List[dict]]:
    """
    Combine image + audio with:
      1) Zoom animation (EXACT logic)
      2) NO subtitles here (subtitles applied after final stitch)

    Returns:
      (audio_duration, word_segments)
    """
    audio_duration = get_audio_duration(audio_path)

    # Extend all clips except first by transition duration
    if is_extended and scene_idx > 0:
        video_duration = audio_duration + TRANSITION_DURATION
    else:
        video_duration = audio_duration

    frames = int(video_duration * FPS)
    zoom_frames = int(frames * ZOOM_SPEED)

    # Random zoom in or zoom out
    start_zoom, end_zoom = random.choice([
        (1.00, MAX_ZOOM),
        (MAX_ZOOM, 1.00)
    ])

    zoom_expr = (
        f"if(lte(n\\,{zoom_frames})\\,"
        f"{start_zoom}+({end_zoom-start_zoom})*"
        f"(1-cos(PI*n/{zoom_frames}))/2\\,"
        f"{end_zoom})"
    )

    # Word-level timestamps (for later subtitle generation)
    lang_for_whisper = normalize_whisper_lang(tts_lang)
    word_segments = get_whisper_subtitles(
        audio_path,
        language=lang_for_whisper,
        expected_text=expected_text,
        audio_duration=audio_duration
    )

    # Video filter (NO SUBTITLES)
    vf = (
        f"scale='max({WIDTH},iw)':'max({HEIGHT},ih)',"
        f"scale=iw*({zoom_expr}):ih*({zoom_expr}):eval=frame,"
        f"crop={WIDTH}:{HEIGHT}:(iw-{WIDTH})/2:(ih-{HEIGHT})/2"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", image_path,
        "-i", audio_path,
        "-vf", vf,
        "-t", str(video_duration),
        "-r", str(FPS),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[✓] Created scene {scene_idx + 1} with animation: {output_path} ({video_duration:.2f}s)")

    return audio_duration, word_segments


def build_scenes(state: Dict[str, Any]) -> Dict[str, Any]:
    """Build individual scene videos with zoom animation"""
    video_dir = "scene_videos"
    os.makedirs(video_dir, exist_ok=True)

    audio_files: List[str] = state.get("audio_files") or []
    image_files: List[str] = state.get("image_files") or []
    voice_overs: List[str] = state.get("voice_overs") or []

    scene_videos: List[str] = []
    scene_durations: List[float] = []
    all_word_segments: List[List[dict]] = []

    total_scenes = min(len(audio_files), len(image_files))
    print(f"\n🎬 Creating {total_scenes} clips with zoom animations...")

    for idx in range(total_scenes):
        audio_path = audio_files[idx]
        image_path = image_files[idx]
        output_path = os.path.join(video_dir, f"scene_{idx+1}.mp4")

        if not os.path.exists(audio_path) or not os.path.exists(image_path):
            print(f"[!] Missing assets for Scene {idx+1}, skipping")
            continue

        expected_text = voice_overs[idx] if idx < len(voice_overs) else None

        base_duration, word_segments = combine_scene_with_animation(
            image_path=image_path,
            audio_path=audio_path,
            output_path=output_path,
            scene_idx=idx,
            is_extended=True,  # Enable extension for xfade
            tts_lang=state.get("tts_lang", "en"),
            expected_text=expected_text
        )

        scene_videos.append(output_path)
        scene_durations.append(base_duration)
        all_word_segments.append(word_segments)

    state["scene_videos"] = scene_videos
    state["scene_durations"] = scene_durations
    state["all_word_segments"] = all_word_segments
    return state


# ============================================
# FINAL STITCHING (xfade video + concat audio)
# Subtitles burned AFTER stitching
# ============================================
def stitch_final_video(state: Dict[str, Any], output_file: str = "final_video.mp4") -> Dict[str, Any]:
    """
    Concatenate scene videos with xfade transitions for VIDEO ONLY.
    Audio is concatenated sequentially (no overlap).
    Subtitles are applied AFTER stitching to avoid overlap.
    """
    scene_videos: List[str] = state.get("scene_videos") or []
    scene_durations: List[float] = state.get("scene_durations") or []
    all_word_segments: List[List[dict]] = state.get("all_word_segments") or []
    audio_files: List[str] = state.get("audio_files") or []

    if not scene_videos:
        print("[!] No scene videos to stitch")
        return state

    os.makedirs("outputs/video", exist_ok=True)

    temp_output = "temp_stitched_no_subs.mp4"

    # If only one clip, just copy it
    if len(scene_videos) == 1:
        subprocess.run(
            ["ffmpeg", "-y", "-i", scene_videos[0], "-c", "copy", temp_output],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    else:
        print(f"\n🔗 Merging {len(scene_videos)} scenes with crossfade transitions...")

        inputs: List[str] = []
        for clip in scene_videos:
            inputs += ["-i", clip]

        filter_complex = ""

        # --- VIDEO XFADE CHAIN ---
        prev_video_label = "0:v"
        if scene_durations:
            cumulative_time = scene_durations[0]
        else:
            cumulative_time = get_audio_duration(audio_files[0]) if audio_files else 0.0

        for i in range(1, len(scene_videos)):
            current_video_label = f"v{i}"
            offset = cumulative_time - TRANSITION_DURATION

            filter_complex += (
                f"[{prev_video_label}][{i}:v]"
                f"xfade=transition=fade:"
                f"duration={TRANSITION_DURATION}:"
                f"offset={offset}"
                f"[{current_video_label}];"
            )

            prev_video_label = current_video_label
            if i < len(scene_durations):
                cumulative_time += scene_durations[i]

        # --- AUDIO CONCATENATION (NO OVERLAP) ---
        audio_labels: List[str] = []
        for i in range(len(scene_videos)):
            duration = scene_durations[i] if i < len(scene_durations) else 5.0
            audio_label = f"a{i}trimmed"
            filter_complex += f"[{i}:a]atrim=0:{duration},asetpts=PTS-STARTPTS[{audio_label}];"
            audio_labels.append(f"[{audio_label}]")

        filter_complex += f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[aout]"

        cmd = (
            ["ffmpeg", "-y"]
            + inputs
            + [
                "-filter_complex", filter_complex,
                "-map", f"[{prev_video_label}]",
                "-map", "[aout]",
                "-r", str(FPS),
                "-pix_fmt", "yuv420p",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "192k",
                temp_output
            ]
        )

        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ============================================
    # APPLY SUBTITLES TO FINAL VIDEO
    # ============================================
    print("\n📝 Applying subtitles to final video...")

    if all_word_segments and any(all_word_segments):
        subtitle_dir = "temp_subtitles"
        os.makedirs(subtitle_dir, exist_ok=True)
        subtitle_path = os.path.join(subtitle_dir, "combined_subtitles.ass")
        generate_combined_ass_subtitles(all_word_segments, scene_durations, subtitle_path)

        # Escape path for FFmpeg filter
        escaped_subtitle_path = subtitle_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

        cmd = [
            "ffmpeg", "-y",
            "-i", temp_output,
            "-vf", f"ass='{escaped_subtitle_path}'",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "copy",
            output_file
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # Clean up temp file
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass
    else:
        # No subtitles, just rename temp to final (overwrite if exists)
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except OSError:
                pass
        os.rename(temp_output, output_file)

    # ============================================
    # DURATION VERIFICATION
    # ============================================
    expected_duration = sum(scene_durations) if scene_durations else 0.0

    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            output_file
        ],
        capture_output=True,
        text=True,
        check=True
    )
    actual_duration = float((result.stdout or "").strip() or "0")

    print(f"\n{'='*60}")
    print("VIDEO CREATION SUMMARY")
    print(f"{'='*60}")
    print(f"Expected duration: {expected_duration:.2f}s")
    print(f"Actual duration: {actual_duration:.2f}s")
    print(f"Difference: {abs(actual_duration - expected_duration):.2f}s")
    print(f"Status: {'✅ PERFECT' if abs(actual_duration - expected_duration) < 0.5 else '⚠️ CHECK'}")
    print(f"{'='*60}\n")

    print(f"[✓] Final video created: {output_file}")

    return state
