# images.py
import os
import json
import time
import base64
import subprocess
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def _get_openrouter_key() -> str:
    k = (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")
    if not k:
        raise ValueError(
            "OPENROUTER_API_KEY is missing/empty at runtime. "
            "Check your .env loading and working directory."
        )
    return k


def create_placeholder_image(output_path: str, text: str = "Scene") -> bool:
    """Create a simple placeholder image using FFmpeg when image generation fails"""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=0x1a1a2e:s=1080x1920:d=1",
        "-vf",
        f"drawtext=text='{text}':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2",
        "-frames:v",
        "1",
        output_path,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError:
        cmd_simple = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x1a1a2e:s=1080x1920:d=1",
            "-frames:v",
            "1",
            output_path,
        ]
        subprocess.run(cmd_simple, check=True, capture_output=True)
        return True


def generate_image(state: Dict[str, Any]) -> Dict[str, Any]:
    image_files: List[str] = []

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=_get_openrouter_key(),
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
        voiceover = scene.get("voiceover", "")
        keywords = scene.get("visual_keywords", "")
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
                max_tokens=100,
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
                    extra_body={"modalities": ["image", "text"]},
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
                    print("    [!] Credit limit reached, creating placeholder image")
                    break

                time.sleep(1)

        if not image_generated:
            print(f"[!] Image generation failed for Scene {scene_id}, creating placeholder")
            if create_placeholder_image(file_path, f"Scene {scene_id}"):
                print(f"[✓] Created placeholder for scene_{scene_id}.jpg")

        image_files.append(file_path)

    state["image_files"] = image_files
    return state
