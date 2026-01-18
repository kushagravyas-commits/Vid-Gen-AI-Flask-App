# template.py
# Applies templates AFTER AI video + subtitles are created (templates t1..t7)
# Special template t9: gameplay + AI audio + subtitles only (no AI video).

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from subtitles import (
    normalize_whisper_lang,
    get_whisper_subtitles,
    generate_combined_ass_subtitles,
)

# Canvas
W, H = 1080, 1920

# Supported templates (t8 removed)
SUPPORTED_TEMPLATES = {
    "t1": "50/50 TOP=AI BOTTOM=GAMEPLAY",
    "t2": "50/50 TOP=GAMEPLAY BOTTOM=AI",
    "t3": "60/40 TOP=AI BOTTOM=GAMEPLAY",
    "t4": "60/40 TOP=GAMEPLAY BOTTOM=AI",
    "t5": "70/30 TOP=AI BOTTOM=GAMEPLAY",
    "t6": "70/30 TOP=GAMEPLAY BOTTOM=AI",
    "t7": "GAMEPLAY BG + AI PIP",
    "t9": "GAMEPLAY + AI AUDIO + SUBS (NO AI VIDEO)",
}


def require_bin(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"Required binary '{name}' not found on PATH.")


def ffprobe_duration(path: str) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path
    ]
    out = subprocess.check_output(cmd, text=True).strip()
    return float(out)


def escape_ass_path(p: str) -> str:
    # Escape for FFmpeg ass='...'
    ap = str(Path(p).resolve()).replace("\\", "/")
    ap = ap.replace(":", "\\:")  # escape drive colon
    ap = ap.replace("'", "\\'")
    return ap


def fit_cover(w: int, h: int) -> str:
    # fill target region, crop overflow
    return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"


def fit_contain(w: int, h: int) -> str:
    # fit inside region, pad
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black"


def split_heights(ratio_top: float) -> Tuple[int, int]:
    top_h = int(round(H * ratio_top))
    bot_h = H - top_h
    return top_h, bot_h


def run_ffmpeg(cmd: List[str]) -> None:
    subprocess.run(cmd, check=True)


def build_filter_split(top_is_ai: bool, ratio_top: float, ai_fit, gp_fit) -> str:
    top_h, bot_h = split_heights(ratio_top)

    # Inputs convention:
    # [0] gameplay (looped)
    # [1] ai video
    ai_top = f"[1:v]{ai_fit(W, top_h)}[ai_top]"
    ai_bot = f"[1:v]{ai_fit(W, bot_h)}[ai_bot]"
    gp_top = f"[0:v]{gp_fit(W, top_h)}[gp_top]"
    gp_bot = f"[0:v]{gp_fit(W, bot_h)}[gp_bot]"

    if top_is_ai:
        # AI top + gameplay bottom
        return ";".join([
            ai_top,
            gp_bot,
            "[ai_top][gp_bot]vstack=inputs=2[v]"
        ])
    else:
        # Gameplay top + AI bottom
        return ";".join([
            gp_top,
            ai_bot,
            "[gp_top][ai_bot]vstack=inputs=2[v]"
        ])


def build_filter_pip_gameplay_bg(ai_fit, gp_fit,
                                pip_w: int, pip_h: int,
                                pip_x: int, pip_y: int,
                                pip_fit) -> str:
    # Gameplay is background, AI is PIP
    bg = f"[0:v]{gp_fit(W, H)}[bg]"
    ov = f"[1:v]{pip_fit(pip_w, pip_h)}[ov]"

    # Add border to PIP (for nicer look)
    bordered = "[ov]pad=w=iw+12:h=ih+12:x=6:y=6:color=white[pip]"
    overlay = f"[bg][pip]overlay=x={pip_x}:y={pip_y}[v]"

    return ";".join([bg, ov, bordered, overlay])


# -------------------------
# TEMPLATE 1..7 (standard)
# -------------------------
def apply_template_to_ai_video(
    template_id: str,
    gameplay_path: str,
    ai_video_path: str,
    output_path: str,
    fps: int = 60,
    crf: int = 20,
    preset: str = "veryfast",
    ai_fit_mode: str = "cover",
    gameplay_fit_mode: str = "cover",
) -> str:
    """
    Applies template t1..t7.
    Final duration is trimmed EXACTLY to AI video duration.
    Gameplay is looped if shorter, but never continues after AI ends.
    Audio is always from AI video.
    """
    if template_id not in SUPPORTED_TEMPLATES or template_id == "t9":
        raise ValueError(f"apply_template_to_ai_video: unsupported template_id={template_id}")

    require_bin("ffmpeg")
    require_bin("ffprobe")

    if not os.path.exists(gameplay_path):
        raise FileNotFoundError(f"Gameplay not found: {gameplay_path}")
    if not os.path.exists(ai_video_path):
        raise FileNotFoundError(f"AI video not found: {ai_video_path}")

    duration = ffprobe_duration(ai_video_path)

    ai_fit = fit_cover if ai_fit_mode == "cover" else fit_contain
    gp_fit = fit_cover if gameplay_fit_mode == "cover" else fit_contain

    # PIP defaults
    pip_w, pip_h = 720, 1280
    pip_x = (W - pip_w) // 2
    pip_y = 60
    pip_fit = fit_contain

    if template_id == "t1":
        fc = build_filter_split(top_is_ai=True, ratio_top=0.5, ai_fit=ai_fit, gp_fit=gp_fit)
    elif template_id == "t2":
        fc = build_filter_split(top_is_ai=False, ratio_top=0.5, ai_fit=ai_fit, gp_fit=gp_fit)
    elif template_id == "t3":
        fc = build_filter_split(top_is_ai=True, ratio_top=0.6, ai_fit=ai_fit, gp_fit=gp_fit)
    elif template_id == "t4":
        fc = build_filter_split(top_is_ai=False, ratio_top=0.6, ai_fit=ai_fit, gp_fit=gp_fit)
    elif template_id == "t5":
        fc = build_filter_split(top_is_ai=True, ratio_top=0.7, ai_fit=ai_fit, gp_fit=gp_fit)
    elif template_id == "t6":
        fc = build_filter_split(top_is_ai=False, ratio_top=0.7, ai_fit=ai_fit, gp_fit=gp_fit)
    elif template_id == "t7":
        # gameplay BG + AI PIP
        fc = build_filter_pip_gameplay_bg(
            ai_fit=ai_fit, gp_fit=gp_fit,
            pip_w=pip_w, pip_h=pip_h, pip_x=pip_x, pip_y=pip_y,
            pip_fit=pip_fit
        )
    else:
        raise ValueError(f"Unknown standard template: {template_id}")

    # Gameplay looped forever, always trimmed to AI duration.
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", gameplay_path,
        "-i", ai_video_path,
        "-filter_complex", fc,
        "-map", "[v]",
        "-map", "1:a?",
        "-t", f"{duration:.3f}",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    run_ffmpeg(cmd)
    return output_path


# -------------------------
# TEMPLATE 9 (special)
# gameplay + concatenated audio + subtitles
# -------------------------
def concat_audio_files(audio_files: List[str], out_audio_path: str) -> str:
    """
    Concatenate mp3s into one mp3 (re-encode for robustness).
    """
    if not audio_files:
        raise ValueError("concat_audio_files: empty audio_files")

    os.makedirs(str(Path(out_audio_path).parent), exist_ok=True)

    list_path = out_audio_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for p in audio_files:
            pn = str(Path(p).resolve()).replace("\\", "/")
            pn = pn.replace("'", "'\\''")
            f.write(f"file '{pn}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", list_path,
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        out_audio_path
    ]
    run_ffmpeg(cmd)

    try:
        os.remove(list_path)
    except OSError:
        pass

    return out_audio_path


def generate_ass_from_audio(
    audio_files: List[str],
    voice_overs: List[str],
    tts_lang: str,
    out_ass_path: str
) -> Tuple[str, float]:
    """
    Builds a single combined ASS using the existing subtitle logic.
    Returns (ass_path, total_audio_duration).
    """
    os.makedirs(str(Path(out_ass_path).parent), exist_ok=True)

    scene_durations: List[float] = []
    all_word_segments: List[List[dict]] = []

    lang_for_whisper = normalize_whisper_lang(tts_lang)

    for i, audio_path in enumerate(audio_files):
        dur = ffprobe_duration(audio_path)
        scene_durations.append(dur)

        expected_text = voice_overs[i] if i < len(voice_overs) else None
        segs = get_whisper_subtitles(
            audio_path,
            language=lang_for_whisper,
            expected_text=expected_text,
            audio_duration=dur
        )
        all_word_segments.append(segs)

    generate_combined_ass_subtitles(all_word_segments, scene_durations, out_ass_path)
    return out_ass_path, float(sum(scene_durations))


def apply_template_9_gameplay_audio_subs(
    gameplay_path: str,
    audio_files: List[str],
    voice_overs: List[str],
    tts_lang: str,
    output_path: str,
    fps: int = 60,
    crf: int = 20,
    preset: str = "veryfast",
    gameplay_fit_mode: str = "cover",
) -> str:
    """
    Template 9:
    - NO AI video.
    - Concatenate audio -> get total audio duration
    - Trim gameplay to audio duration (loop if needed)
    - Burn subtitles (ASS) on top of gameplay using existing ASS logic
    """
    require_bin("ffmpeg")
    require_bin("ffprobe")

    if not os.path.exists(gameplay_path):
        raise FileNotFoundError(f"Gameplay not found: {gameplay_path}")
    if not audio_files:
        raise ValueError("Template 9 requires audio_files")

    tmp_dir = Path("temp_template9")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    combined_audio = str(tmp_dir / "combined_audio.mp3")
    combined_audio = concat_audio_files(audio_files, combined_audio)
    audio_duration = ffprobe_duration(combined_audio)

    subs_ass = str(tmp_dir / "combined_subtitles.ass")
    subs_ass, _ = generate_ass_from_audio(audio_files, voice_overs, tts_lang, subs_ass)

    gp_fit = fit_cover if gameplay_fit_mode == "cover" else fit_contain

    # Gameplay full background + burn subs; audio is the combined AI audio
    # Trim everything to audio duration (so gameplay never continues after audio ends)
    sp = escape_ass_path(subs_ass)
    vf = f"{gp_fit(W, H)},ass='{sp}'"

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", gameplay_path,
        "-i", combined_audio,
        "-vf", vf,
        "-map", "0:v",
        "-map", "1:a",
        "-t", f"{audio_duration:.3f}",
        "-r", str(fps),
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-preset", preset,
        "-crf", str(crf),
        "-c:a", "aac",
        "-b:a", "192k",
        output_path
    ]
    run_ffmpeg(cmd)
    return output_path


def apply_template_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Dispatcher used by workflow_app.py
    Requires:
      - template_id
      - gameplay_video_path
      - output_file
    For t1..t7: requires ai_video_path
    For t9: requires audio_files + voice_overs + tts_lang
    """
    template_id = str(state.get("template_id") or "").strip()
    if template_id not in SUPPORTED_TEMPLATES:
        raise ValueError(f"Unknown template_id='{template_id}'. Supported: {list(SUPPORTED_TEMPLATES.keys())}")

    gameplay = str(state.get("gameplay_video_path") or "").strip()
    out_file = str(state.get("output_file") or "final_video.mp4").strip()

    fps = int(state.get("template_fps") or 60)
    crf = int(state.get("template_crf") or 20)
    preset = str(state.get("template_preset") or "veryfast")
    ai_fit_mode = str(state.get("template_ai_fit") or "cover")
    gp_fit_mode = str(state.get("template_gp_fit") or "cover")

    if template_id == "t9":
        audio_files = state.get("audio_files") or []
        voice_overs = state.get("voice_overs") or []
        tts_lang = str(state.get("tts_lang") or "en")
        final_path = apply_template_9_gameplay_audio_subs(
            gameplay_path=gameplay,
            audio_files=audio_files,
            voice_overs=voice_overs,
            tts_lang=tts_lang,
            output_path=out_file,
            fps=fps,
            crf=crf,
            preset=preset,
            gameplay_fit_mode=gp_fit_mode
        )
        return {"final_video_path": final_path}

    # standard templates require ai_video_path
    ai_video_path = str(state.get("ai_video_path") or "").strip()
    if not ai_video_path:
        raise ValueError(f"Template {template_id} requires ai_video_path in state.")

    final_path = apply_template_to_ai_video(
        template_id=template_id,
        gameplay_path=gameplay,
        ai_video_path=ai_video_path,
        output_path=out_file,
        fps=fps,
        crf=crf,
        preset=preset,
        ai_fit_mode=ai_fit_mode,
        gameplay_fit_mode=gp_fit_mode
    )
    return {"final_video_path": final_path}
