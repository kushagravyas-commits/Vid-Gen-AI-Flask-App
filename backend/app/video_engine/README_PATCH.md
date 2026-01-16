# Video Generator Integration (Do NOT change logic)

Place your existing LangGraph video generator code into:

- `backend/app/video_engine/video_generator.py`

Then apply the patch in `video_generator.patch` (minimal fixes only):
- Fix PromptTemplate variables mismatch (languages/style placeholders)
- Accept `languages` and `style` in `inputs`
- Use `tts_lang` from state for `gTTS(lang=...)` so audio matches chosen Indian language

The rest of your logic (FFmpeg, Whisper, zoom, xfade, subtitles) remains unchanged.

If you want *multiple languages* per job, the backend will run the pipeline once per language
in an isolated folder and zip the outputs.
