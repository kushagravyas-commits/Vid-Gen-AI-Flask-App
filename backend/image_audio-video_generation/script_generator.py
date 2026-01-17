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
    """Remove ```json fences and extract the JSON object."""
    if not isinstance(text, str):
        return text

    t = text.strip()

    # Remove opening fence like ```json or ```
    t = re.sub(r"^\s*```[a-zA-Z]*\s*", "", t)

    # Remove closing fence ```
    t = re.sub(r"\s*```\s*$", "", t)

    t = t.strip()

    # Extract the first {...} block
    start = t.find("{")
    end = t.rfind("}")
    if start != -1 and end != -1 and end > start:
        t = t[start : end + 1]

    return t


def _get_openrouter_key() -> str:
    k = (os.getenv("OPENROUTER_API_KEY") or "").strip().strip('"').strip("'")
    if not k:
        raise ValueError(
            "OPENROUTER_API_KEY is missing/empty at runtime. "
            "Check your .env loading and working directory."
        )
    return k


def generate_script(state: Dict[str, Any]) -> Dict[str, Any]:
    prompt_string = """
You are an expert political content creator and video editor. Your task is to generate a script for faceless vertical video (9:16).

Instructions:
- Split the script into scenes based on visual changes
- For each scene, provide the spoken text and 3 keywords for stock footage search
- Use an attention-grabbing 'Hook' in the first 3 seconds
- End with a 'Call to Action'
- Whatever the time is given by the user, divide the scenes into that time.
- you have to assign the expected time in seconds for each scene accrding to the length of the voiceover in each scene.
- Write the expected time in seconds for each scene according to the voiceover.
- There is no limit of scenes, you can create as many scenes as you want.
- In the voiceover you also have to write the tone. You have to select the tone only from the below options - 
    "laughs", "laughs harder", "starts laughing", "wheezing",
    "whispers", "shouts",
    "sighs", "exhales", "clears throat", "coughs", "gasps", "snorts",
    "sarcastic", "curious", "excited", "crying", "mischievously",
    "sad", "angry", "happily",
    "applause", "clapping", "gunshot", "explosion", "swallows", "gulps",
    "slowly", "quickly", "chuckles".
- Always write the tone in inside the '[]' bracket. Eg: [laughs],[sad],[exhales],[coughs]. 
- IMPORTANT: Write ALL "voiceover" text strictly in {languages}. Do NOT use English (except proper nouns). Use the native script (e.g., हिन्दी, বাংলা, தமிழ்).
- Target language code: {tts_lang}. Use this to decide the exact language/script.
- ABSOLUTE RULE: The "voiceover" must be written ONLY in the target language's native script. 
  If tts_lang is "hi", use Devanagari only (हिन्दी). No Roman letters, no English words.

- Output strictly in JSON format with this structure:

{{
  "metadata": {{
    "topic": "<topic_name>",
    "language": "{languages}",
    "style": "{style}",
    "total_estimated_duration": "<duration>"
  }},
  "video_script": [
    {{
      "scene_id": 1,
      "expected_time_in_seconds": "expected_time_in_seconds",
      "voiceover": "spoken text",
      "visual_keywords": "keyword1, keyword2, keyword3",
      "overlay_text": "TEXT"
    }}
  ]
}}

Now generate a script for the following query:
{query}

Remember: Your response must be ONLY valid JSON, nothing else.
    """

    prompt = PromptTemplate(
        input_variables=["query", "languages", "style", "tts_lang"],
        template=prompt_string,
    )

    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=_get_openrouter_key(),
    )

    response = client.chat.completions.create(
        model="nvidia/nemotron-3-nano-30b-a3b:free",
        messages=[
            {
                "role": "system",
                "content": "You are a video script generator. Always respond with valid JSON only. Follow the user's exact query topic.",
            },
            {
                "role": "user",
                "content": prompt.format(
                    query=state["user_query"],
                    languages=", ".join(state.get("languages", []))
                    if isinstance(state.get("languages"), list)
                    else str(state.get("languages", "")),
                    style=str(state.get("style", "")),
                    tts_lang=str(state.get("tts_lang", "en")),
                ),
            },
        ],
        extra_body={"reasoning": {"enabled": True}},
    )

    script = response.choices[0].message.content
    script = sanitize_model_json(script)
    return {"video_script": script}


def extract_script(state: Dict[str, Any]) -> Dict[str, Any]:
    try:
        clean = sanitize_model_json(state["video_script"])
        script_data = json.loads(clean)

        voice_overs = []
        for scene in script_data.get("video_script", []):
            voiceover = scene.get("voiceover", "")
            if voiceover:
                voice_overs.append(voiceover)

        print(f"Extracted {len(voice_overs)} voiceovers")
        return {"voice_overs": voice_overs}

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid script JSON: {state['video_script']}") from e
