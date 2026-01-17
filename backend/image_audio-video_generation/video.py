# video.py
import os
import subprocess
import random
from typing import Any, Dict, List, Optional, Tuple

from subtitles import normalize_whisper_lang, get_whisper_subtitles, generate_combined_ass_subtitles

FPS = 60
WIDTH = 1080
HEIGHT = 1920
TRANSITION_DURATION = 1.0
MAX_ZOOM = 1.08
ZOOM_SPEED = 0.7


def get_audio_duration(audio_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        audio_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return float((r.stdout or "").strip() or "0")


def get_video_duration(video_path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        video_path
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return float((r.stdout or "").strip() or "0")


def combine_scene_with_animation(
    image_path: str,
    audio_path: str,
    output_path: str,
    scene_idx: int,
    is_extended: bool = True,
    tts_lang: Optional[str] = None,
    expected_text: Optional[str] = None,
) -> Tuple[float, List[dict]]:
    """
    IMPORTANT:
    - Base scene duration = actual audio duration (NO pause insertion).
    - Video is extended by TRANSITION_DURATION for non-first clips to support xfade.
      That extra tail is trimmed out of final AUDIO in stitch step.
    """
    audio_duration = get_audio_duration(audio_path)

    # extend VIDEO only for xfade chain
    if is_extended and scene_idx > 0:
        video_duration = audio_duration + TRANSITION_DURATION
    else:
        video_duration = audio_duration

    frames = int(video_duration * FPS)
    zoom_frames = int(frames * ZOOM_SPEED)

    start_zoom, end_zoom = random.choice([(1.00, MAX_ZOOM), (MAX_ZOOM, 1.00)])
    zoom_expr = (
        f"if(lte(n\\,{zoom_frames})\\,"
        f"{start_zoom}+({end_zoom-start_zoom})*"
        f"(1-cos(PI*n/{zoom_frames}))/2\\,"
        f"{end_zoom})"
    )

    # subtitles for spoken part only
    lang_for_whisper = normalize_whisper_lang(tts_lang)
    word_segments = get_whisper_subtitles(
        audio_path,
        language=lang_for_whisper,
        expected_text=expected_text,
        audio_duration=audio_duration
    )

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
    print(f"[✓] Scene {scene_idx+1}: voice={audio_duration:.2f}s, video_total={video_duration:.2f}s -> {output_path}")
    return audio_duration, word_segments


def build_scenes(state: Dict[str, Any]) -> Dict[str, Any]:
    video_dir = "scene_videos"
    os.makedirs(video_dir, exist_ok=True)

    audio_files: List[str] = state.get("audio_files") or []
    image_files: List[str] = state.get("image_files") or []
    voice_overs: List[str] = state.get("voice_overs") or []

    total_scenes = min(len(audio_files), len(image_files))
    print(f"\n🎬 Creating {total_scenes} clips...")

    scene_videos: List[str] = []
    scene_durations: List[float] = []        # base audio durations (NO pause)
    all_word_segments: List[List[dict]] = []

    for idx in range(total_scenes):
        audio_path = audio_files[idx]
        image_path = image_files[idx]
        output_path = os.path.join(video_dir, f"scene_{idx+1}.mp4")

        if not os.path.exists(audio_path) or not os.path.exists(image_path):
            print(f"[!] Missing assets for Scene {idx+1}, skipping")
            continue

        expected_text = voice_overs[idx] if idx < len(voice_overs) else None
        base_dur, word_segments = combine_scene_with_animation(
            image_path=image_path,
            audio_path=audio_path,
            output_path=output_path,
            scene_idx=idx,
            is_extended=True,
            tts_lang=state.get("tts_lang", "en"),
            expected_text=expected_text
        )

        scene_videos.append(output_path)
        scene_durations.append(base_dur)
        all_word_segments.append(word_segments)

    state["scene_videos"] = scene_videos
    state["scene_durations"] = scene_durations
    state["all_word_segments"] = all_word_segments
    return state


def stitch_final_video(state: Dict[str, Any], output_file: str = "final_video.mp4") -> Dict[str, Any]:
    scene_videos: List[str] = state.get("scene_videos") or []
    scene_durations: List[float] = state.get("scene_durations") or []
    all_word_segments: List[List[dict]] = state.get("all_word_segments") or []
    audio_files: List[str] = state.get("audio_files") or []

    if not scene_videos:
        print("[!] No scene videos to stitch")
        return state

    temp_output = "temp_stitched_no_subs.mp4"

    if len(scene_videos) == 1:
        subprocess.run(["ffmpeg", "-y", "-i", scene_videos[0], "-c", "copy", temp_output],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        print(f"\n🔗 Merging {len(scene_videos)} scenes with xfade...")
        inputs: List[str] = []
        for clip in scene_videos:
            inputs += ["-i", clip]

        filter_complex = ""

        prev_video_label = "0:v"
        cumulative_time = scene_durations[0] if scene_durations else (get_audio_duration(audio_files[0]) if audio_files else 0.0)

        for i in range(1, len(scene_videos)):
            current_video_label = f"v{i}"
            offset = cumulative_time - TRANSITION_DURATION
            filter_complex += (
                f"[{prev_video_label}][{i}:v]"
                f"xfade=transition=fade:duration={TRANSITION_DURATION}:offset={offset}"
                f"[{current_video_label}];"
            )
            prev_video_label = current_video_label
            if i < len(scene_durations):
                cumulative_time += scene_durations[i]

        # AUDIO concat (trim to base audio durations; removes xfade tail silence)
        audio_labels: List[str] = []
        for i in range(len(scene_videos)):
            duration = scene_durations[i] if i < len(scene_durations) else 5.0
            audio_label = f"a{i}trimmed"
            filter_complex += f"[{i}:a]atrim=0:{duration},asetpts=PTS-STARTPTS[{audio_label}];"
            audio_labels.append(f"[{audio_label}]")

        filter_complex += f"{''.join(audio_labels)}concat=n={len(audio_labels)}:v=0:a=1[aout]"

        cmd = (["ffmpeg", "-y"] + inputs + [
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
        ])
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Burn subtitles AFTER stitch
    print("\n📝 Applying subtitles...")
    if all_word_segments and any(all_word_segments):
        os.makedirs("temp_subtitles", exist_ok=True)
        subtitle_path = os.path.join("temp_subtitles", "combined_subtitles.ass")
        generate_combined_ass_subtitles(all_word_segments, scene_durations, subtitle_path)

        escaped = subtitle_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
        subprocess.run(
            ["ffmpeg", "-y", "-i", temp_output, "-vf", f"ass='{escaped}'",
             "-c:v", "libx264", "-preset", "fast", "-crf", "23", "-c:a", "copy", output_file],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try: os.remove(temp_output)
        except OSError: pass
    else:
        if os.path.exists(output_file):
            try: os.remove(output_file)
            except OSError: pass
        os.rename(temp_output, output_file)

    dur = get_video_duration(output_file)
    print(f"\n[✓] Final video created: {output_file} ({dur:.2f}s)")
    return state
