"""실시간 비용 추적"""
import json
import threading
from pathlib import Path
from datetime import datetime

LYRIA_COST_PER_TRACK = 0.08
GEMINI_INPUT_COST_PER_M = 0.15    # Gemini 2.5 Flash
GEMINI_OUTPUT_COST_PER_M = 0.60
KRW_PER_USD = 1350


class CostTracker:
    def __init__(self, persist_path: Path = None):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._persist_path = persist_path or Path("cost_history.json")

    def init_job(self, job_id: str):
        with self._lock:
            self._jobs[job_id] = {
                "lyria_tracks": 0,
                "lyria_cost": 0.0,
                "gemini_input_tokens": 0,
                "gemini_output_tokens": 0,
                "gemini_cost": 0.0,
                "total_cost": 0.0,
                "started_at": datetime.now().isoformat(),
            }

    def add_lyria(self, job_id: str, count: int = 1):
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["lyria_tracks"] += count
            j["lyria_cost"] = j["lyria_tracks"] * LYRIA_COST_PER_TRACK
            j["total_cost"] = j["lyria_cost"] + j["gemini_cost"]

    def add_gemini(self, job_id: str, input_tokens: int, output_tokens: int):
        with self._lock:
            j = self._jobs.get(job_id)
            if not j:
                return
            j["gemini_input_tokens"] += input_tokens
            j["gemini_output_tokens"] += output_tokens
            j["gemini_cost"] = (
                j["gemini_input_tokens"] / 1_000_000 * GEMINI_INPUT_COST_PER_M
                + j["gemini_output_tokens"] / 1_000_000 * GEMINI_OUTPUT_COST_PER_M
            )
            j["total_cost"] = j["lyria_cost"] + j["gemini_cost"]

    def get_job_cost(self, job_id: str) -> dict:
        with self._lock:
            j = self._jobs.get(job_id, {})
            return {
                **j,
                "total_krw": int(j.get("total_cost", 0) * KRW_PER_USD),
            }

    def get_total(self) -> dict:
        with self._lock:
            total = sum(j["total_cost"] for j in self._jobs.values())
            tracks = sum(j["lyria_tracks"] for j in self._jobs.values())
            return {
                "total_usd": round(total, 4),
                "total_krw": int(total * KRW_PER_USD),
                "total_tracks": tracks,
                "jobs": len(self._jobs),
            }


cost_tracker = CostTracker()
