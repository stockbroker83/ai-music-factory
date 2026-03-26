"""설정 관리"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ENV_PATH = Path(__file__).parent.parent / ".env"
load_dotenv(ENV_PATH)

# playlist.py에서 프리셋 가져오기
sys.path.insert(0, str(Path(__file__).parent.parent))
from playlist import PRESETS


def get_config() -> dict:
    return {
        "ANTHROPIC_API_KEY": os.getenv("ANTHROPIC_API_KEY", ""),
        "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", ""),
        "YT_PRIVACY": os.getenv("YT_PRIVACY", "unlisted"),
        "PLAYLIST_OUTPUT_DIR": os.getenv(
            "PLAYLIST_OUTPUT_DIR", str(Path.home() / "music" / "AI_Playlist")
        ),
    }


def save_config(updates: dict):
    """updates 딕셔너리의 키-값을 .env 파일에 반영"""
    lines = []
    existing_keys = set()

    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if "=" in stripped and not stripped.startswith("#"):
                key = stripped.split("=", 1)[0].strip()
                if key in updates:
                    lines.append(f"{key}={updates[key]}")
                    existing_keys.add(key)
                else:
                    lines.append(line)
            else:
                lines.append(line)

    for key, val in updates.items():
        if key not in existing_keys:
            lines.append(f"{key}={val}")

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    load_dotenv(ENV_PATH, override=True)


def get_presets() -> dict:
    return PRESETS


def validate() -> list[str]:
    issues = []
    cfg = get_config()
    if not cfg["ANTHROPIC_API_KEY"]:
        issues.append("ANTHROPIC_API_KEY 미설정")
    if not cfg["GEMINI_API_KEY"]:
        issues.append("GEMINI_API_KEY 미설정")
    return issues
