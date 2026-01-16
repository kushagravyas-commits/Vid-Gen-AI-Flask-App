from __future__ import annotations

import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


load_dotenv()


@dataclass(frozen=True)
class Settings:
    JOBS_DIR: str = os.getenv("JOBS_DIR", "jobs")
    MAX_WORKERS: int = int(os.getenv("MAX_WORKERS", "1"))

    # ✅ FIX: use default_factory for list
    CORS_ALLOW_ORIGINS: list[str] = field(
        default_factory=lambda: os.getenv(
            "CORS_ALLOW_ORIGINS", "http://localhost:5000"
        ).split(",")
    )

    # ✅ FIX: also list default should be via default_factory
    STYLES: list[str] = field(
        default_factory=lambda: (
            os.getenv("STYLES", "").split(",")
            if os.getenv("STYLES")
            else [
                "Cinematic",
                "Documentary",
                "Newsroom",
                "Minimal",
                "Bold Typography",
                "Vintage Film",
                "Noir",
                "Neon Cyber",
                "Corporate",
                "Explainer",
                "Infographic",
                "Anime",
                "Digital Art",
                "3D Render",
                "Retro Pop",
                "Moody",
                "Warm",
                "Cold",
                "High Contrast",
                "Soft Pastel",
                "Vlog",
                "Travel",
                "Tech",
                "Sports",
                "Political Satire",
                "Historic",
                "Modern India",
                "Street",
                "Nature",
                "Architecture",
                "Finance",
                "Education",
                "Healthcare",
                "Defense",
                "Space",
                "Agriculture",
                "Governance",
                "Startup",
                "Luxury",
                "Motivational",
                "Dark Theme",
                "Light Theme",
                "Fast Cuts",
                "Slow Pace",
                "Emotional",
                "Energetic",
                "Dramatic",
                "Humorous",
                "Serious",
                "Youth",
                "Professional",
                "Premium",
            ]
        )
    )

settings = Settings()
