"""Indian language codes and display names for UI + backend validation.

NOTE: This list is inclusive (22 scheduled languages + common variants).
Your TTS provider must support the selected code. In the patched generator,
gTTS is used; if a code isn't supported by gTTS in your environment,
you can either (a) switch TTS provider OR (b) map it to a supported variant.
"""

INDIAN_LANGUAGES = {
    # Widely supported
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "te": "Telugu",
    "ta": "Tamil",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
    "or": "Odia",
    "as": "Assamese",

    # Additional Indian languages (may need a different TTS engine if gTTS lacks them)
    "sa": "Sanskrit",
    "ne": "Nepali",
    "sd": "Sindhi",
    "si": "Sinhala",
    "kok": "Konkani",
    "mai": "Maithili",
    "doi": "Dogri",
    "ks": "Kashmiri",
    "mni": "Manipuri (Meitei)",
    "brx": "Bodo",
    "sat": "Santali",

    # Common variants
    "en-in": "English (India)",
    "hi-in": "Hindi (India)",
    "bn-in": "Bengali (India)",
    "ta-in": "Tamil (India)",
    "te-in": "Telugu (India)",
}
