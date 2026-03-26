"""작업 관리자 — 병렬 컨셉 생성 + 실시간 이벤트 + 디스크 영속성"""
import sys
import uuid
import json
import time
import threading
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.event_bus import event_bus
from core.cost_tracker import cost_tracker

# playlist.py 함수들 임포트
from playlist import (
    research_trends,
    opus_viral_concept_upgrade,
    opus_design_playlist,
    generate_one_track,
    post_process_audio,
    get_audio_duration,
    safe_filename,
    check_deps,
    PRESETS,
    BETWEEN_TRACKS_DELAY,
    LYRIA_COST_PER_TRACK,
)

JOBS_FILE = Path(__file__).parent.parent / "jobs_history.json"
OUTPUT_DIR = Path.home() / "music" / "AI_Playlist"


class Job:
    def __init__(self, config: dict):
        self.id = str(uuid.uuid4())[:8]
        self.config = config
        self.status = "pending"
        self.concepts = []
        self.tracks = []
        self.logs = []
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.output_dir = None
        self.source = "web"  # "web" or "cli"

    def to_dict(self):
        success = sum(1 for t in self.tracks if t.get("status") == "success")
        failed = sum(1 for t in self.tracks if t.get("status") == "failed")
        return {
            "id": self.id,
            "status": self.status,
            "config": self.config,
            "concepts": self.concepts,
            "tracks": self.tracks,
            "logs": self.logs[-200:],
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "output_dir": self.output_dir,
            "success_count": success,
            "failed_count": failed,
            "total_count": len(self.tracks),
            "cost": cost_tracker.get_job_cost(self.id),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        """디스크에서 복원"""
        job = cls.__new__(cls)
        job.id = data["id"]
        job.config = data.get("config", {})
        job.status = data.get("status", "complete")
        job.concepts = data.get("concepts", [])
        job.tracks = data.get("tracks", [])
        job.logs = data.get("logs", [])
        job.created_at = data.get("created_at", "")
        job.started_at = data.get("started_at", "")
        job.completed_at = data.get("completed_at", "")
        job.error = data.get("error")
        job.output_dir = data.get("output_dir")
        job.source = data.get("source", "web")
        return job

    @classmethod
    def from_playlist_info(cls, info: dict, folder_path: Path) -> "Job":
        """CLI로 생성된 _playlist_info.json에서 Job 복원"""
        job = cls.__new__(cls)
        # 폴더명 해시로 유니크 ID 생성
        import hashlib
        h = hashlib.md5(folder_path.name.encode()).hexdigest()[:6]
        job.id = f"cli-{h}"
        job.source = "cli"

        concept = info.get("concept", {})
        job.config = {
            "mode": "auto",
            "count": info.get("success", 0) + info.get("failed", 0),
        }
        job.concepts = [concept] if concept else []
        job.status = "complete"
        job.created_at = info.get("created_at", "")
        job.started_at = info.get("created_at", "")

        # elapsed_min에서 completed_at 역산
        elapsed_min = info.get("elapsed_min", 0)
        if job.started_at and elapsed_min:
            try:
                start = datetime.fromisoformat(job.started_at)
                from datetime import timedelta
                job.completed_at = (start + timedelta(minutes=elapsed_min)).isoformat()
            except Exception:
                job.completed_at = job.started_at
        else:
            job.completed_at = job.started_at

        job.output_dir = str(folder_path)
        job.error = None
        job.logs = []

        # 트랙 정보 복원
        job.tracks = []
        for t in info.get("tracks", []):
            track_info = {
                "track_number": t.get("track_number", 0),
                "title_ko": t.get("title_ko", ""),
                "title_en": t.get("filename", "").replace(".mp3", ""),
                "status": t.get("status", "success"),
                "filename": t.get("filename", ""),
                "duration_sec": t.get("duration_sec", 0),
                "size_kb": t.get("size_kb", 0),
                "path": str(folder_path / t.get("filename", "")) if t.get("filename") else "",
            }
            job.tracks.append(track_info)

        return job


class JobManager:
    def __init__(self, max_workers: int = 3):
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._load_from_disk()
        self._scan_cli_history()

    def _load_from_disk(self):
        """서버 재시작 시 이전 웹 작업 복원"""
        if not JOBS_FILE.exists():
            return
        try:
            data = json.loads(JOBS_FILE.read_text(encoding="utf-8"))
            for item in data:
                job = Job.from_dict(item)
                self._jobs[job.id] = job
                # 비용 정보도 복원
                cost_data = item.get("cost", {})
                if cost_data:
                    cost_tracker.init_job(job.id)
                    lyria = cost_data.get("lyria_tracks", 0)
                    if lyria:
                        cost_tracker.add_lyria(job.id, lyria)
        except Exception as e:
            print(f"[JobManager] 히스토리 로드 실패: {e}")

    def _scan_cli_history(self):
        """CLI로 생성된 폴더의 _playlist_info.json 스캔"""
        if not OUTPUT_DIR.exists():
            return
        existing_dirs = {
            Path(j.output_dir).name
            for j in self._jobs.values()
            if j.output_dir
        }
        for d in OUTPUT_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("_"):
                continue
            if d.name in existing_dirs:
                continue
            info_file = d / "_playlist_info.json"
            if not info_file.exists():
                continue
            try:
                info = json.loads(info_file.read_text(encoding="utf-8"))
                job = Job.from_playlist_info(info, d)
                self._jobs[job.id] = job
                # 비용 복원
                cost_usd = info.get("cost_usd", 0)
                if cost_usd > 0:
                    cost_tracker.init_job(job.id)
                    lyria_count = info.get("success", 0)
                    if lyria_count:
                        cost_tracker.add_lyria(job.id, lyria_count)
            except Exception as e:
                print(f"[JobManager] CLI 히스토리 스캔 실패 ({d.name}): {e}")

    def _save_to_disk(self):
        """완료된 웹 작업을 디스크에 저장"""
        with self._lock:
            web_jobs = [
                j.to_dict() for j in self._jobs.values()
                if j.source == "web" and j.status in ("complete", "failed", "cancelled")
            ]
        try:
            JOBS_FILE.write_text(
                json.dumps(web_jobs, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            print(f"[JobManager] 저장 실패: {e}")

    def create_job(self, config: dict) -> Job:
        job = Job(config)
        with self._lock:
            self._jobs[job.id] = job
        cost_tracker.init_job(job.id)
        event_bus.publish("job_created", {"config": config}, job.id)
        self._executor.submit(self._run_job, job)
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list_jobs(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in reversed(list(self._jobs.values()))]

    def cancel_job(self, job_id: str):
        job = self._jobs.get(job_id)
        if job and job.status in ("pending", "researching", "designing", "generating"):
            job.status = "cancelled"
            job.completed_at = datetime.now().isoformat()
            event_bus.publish("job_cancelled", {}, job.id)
            self._save_to_disk()

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
        if job:
            self._save_to_disk()
            return True
        return False

    def get_disk_stats(self) -> dict:
        """전체 디스크 음악 통계"""
        if not OUTPUT_DIR.exists():
            return {"total_tracks": 0, "total_duration_min": 0, "total_size_mb": 0, "folder_count": 0}

        total_tracks = 0
        total_size = 0
        total_duration = 0
        folder_count = 0

        for d in OUTPUT_DIR.iterdir():
            if not d.is_dir() or d.name.startswith("_"):
                continue
            folder_count += 1
            info_file = d / "_playlist_info.json"
            if info_file.exists():
                try:
                    info = json.loads(info_file.read_text(encoding="utf-8"))
                    total_tracks += info.get("success", 0)
                    total_duration += info.get("total_duration_min", 0)
                    total_size += info.get("total_size_mb", 0)
                    continue
                except Exception:
                    pass
            # _playlist_info.json 없으면 직접 스캔
            mp3s = list(d.glob("*.mp3"))
            total_tracks += len(mp3s)
            total_size += sum(f.stat().st_size for f in mp3s) / (1024 * 1024)

        return {
            "total_tracks": total_tracks,
            "total_duration_min": round(total_duration, 1),
            "total_size_mb": round(total_size, 1),
            "folder_count": folder_count,
        }

    def _log(self, job: Job, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        job.logs.append(line)
        event_bus.publish("log_line", {"message": line}, job.id)

    def _run_job(self, job: Job):
        try:
            job.started_at = datetime.now().isoformat()
            job.status = "researching"
            event_bus.publish("job_started", {"status": "researching"}, job.id)

            mode = job.config.get("mode", "auto")
            count = job.config.get("count", 20)
            output_dir = job.config.get("output_dir", str(OUTPUT_DIR))
            job.output_dir = output_dir

            # 컨셉 결정
            if mode == "auto":
                self._log(job, "트렌드 리서치 시작...")
                trends = research_trends()
                self._log(job, "트렌드 리서치 완료")

                job.status = "designing"
                event_bus.publish("step_changed", {"step": "designing"}, job.id)

                num_concepts = job.config.get("num_concepts", 1)
                hint = job.config.get("hint", "")
                self._log(job, f"바이럴 컨셉 {num_concepts}개 생성 중...")
                concepts = opus_viral_concept_upgrade(
                    trends["trend_data"], num_concepts=num_concepts, user_hint=hint
                )
                job.concepts = concepts
                for i, c in enumerate(concepts):
                    self._log(job, f"  컨셉 {i+1}: {c.get('concept_name', 'N/A')}")
                event_bus.publish("concepts_ready", {"concepts": concepts}, job.id)

            elif mode == "preset":
                preset_key = job.config.get("preset_key", "cafe_morning")
                preset = PRESETS.get(preset_key, list(PRESETS.values())[0])
                concepts = [{**preset, "concept_name": preset["name"]}]
                job.concepts = concepts
                self._log(job, f"프리셋 사용: {preset['name']}")
                event_bus.publish("concepts_ready", {"concepts": concepts}, job.id)

            elif mode == "manual":
                concept_text = job.config.get("concept", "")
                concepts = [{"concept_name": concept_text, "description": concept_text}]
                job.concepts = concepts
                self._log(job, f"수동 컨셉: {concept_text}")
                event_bus.publish("concepts_ready", {"concepts": concepts}, job.id)
            else:
                concepts = [{"concept_name": "Default", "description": "Default concept"}]
                job.concepts = concepts

            # 병렬 컨셉 처리
            parallel = job.config.get("parallel_concepts", False) and len(concepts) > 1
            job.status = "generating"
            event_bus.publish("step_changed", {"step": "generating"}, job.id)

            if parallel:
                self._log(job, f"병렬 모드: {len(concepts)}개 컨셉 동시 생성")
                futures = {}
                with ThreadPoolExecutor(max_workers=min(len(concepts), 3)) as pool:
                    for ci, concept in enumerate(concepts):
                        f = pool.submit(
                            self._generate_concept, job, concept, ci, count, output_dir
                        )
                        futures[f] = ci
                    for f in as_completed(futures):
                        ci = futures[f]
                        try:
                            f.result()
                        except Exception as e:
                            self._log(job, f"컨셉 {ci+1} 오류: {e}")
            else:
                for ci, concept in enumerate(concepts):
                    if job.status == "cancelled":
                        break
                    self._generate_concept(job, concept, ci, count, output_dir)

            job.status = "complete"
            job.completed_at = datetime.now().isoformat()
            cost = cost_tracker.get_job_cost(job.id)
            event_bus.publish("job_complete", {"cost": cost}, job.id)
            self._log(job, f"완료! 비용: ${cost.get('total_cost', 0):.2f} (₩{cost.get('total_krw', 0):,})")
            self._save_to_disk()

        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.completed_at = datetime.now().isoformat()
            event_bus.publish("job_error", {"error": str(e)}, job.id)
            self._log(job, f"오류: {e}")
            self._save_to_disk()

    def _generate_concept(self, job: Job, concept: dict, concept_idx: int, count: int, output_dir: str):
        concept_name = concept.get("concept_name", concept.get("name", "unnamed"))
        self._log(job, f"[컨셉 {concept_idx+1}] '{concept_name}' 트랙 설계 중...")

        tracks = opus_design_playlist(concept, count)
        self._log(job, f"[컨셉 {concept_idx+1}] {len(tracks)}곡 설계 완료")

        today = datetime.now().strftime("%Y%m%d")
        folder_name = f"{today}_{safe_filename(concept_name)}"
        playlist_dir = Path(output_dir) / folder_name
        playlist_dir.mkdir(parents=True, exist_ok=True)
        job.output_dir = str(playlist_dir)

        has_ffmpeg = True
        try:
            import subprocess
            subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        except Exception:
            has_ffmpeg = False

        for i, track in enumerate(tracks):
            if job.status == "cancelled":
                self._log(job, "작업 취소됨")
                return

            num = track["track_number"]
            title_en = safe_filename(track.get("title_en", f"track_{num:02d}"), 30)
            title_ko = track.get("title_ko", f"트랙 {num}")

            track_info = {
                "concept_idx": concept_idx,
                "track_number": num,
                "title_ko": title_ko,
                "title_en": title_en,
                "status": "generating",
                "lyria_prompt": track.get("lyria_prompt", ""),
            }
            job.tracks.append(track_info)
            event_bus.publish("track_progress", {
                "concept_idx": concept_idx,
                "track_number": num,
                "title_ko": title_ko,
                "status": "generating",
                "progress": f"{i+1}/{len(tracks)}",
            }, job.id)
            self._log(job, f"  [{num:02d}/{len(tracks)}] {title_ko} 생성 중...")

            raw_path = playlist_dir / f"_raw_{num:02d}_{title_en}"
            audio = generate_one_track(track["lyria_prompt"], raw_path, use_pro=True)

            if audio and audio.exists():
                cost_tracker.add_lyria(job.id)

                final_name = f"{num:02d}_{title_en}.mp3"
                final_path = playlist_dir / final_name

                if has_ffmpeg:
                    final_path = post_process_audio(audio, final_path)
                    if audio != final_path and audio.exists():
                        try:
                            audio.unlink()
                        except Exception:
                            pass
                else:
                    try:
                        audio.rename(final_path)
                    except Exception:
                        final_path = audio

                dur = get_audio_duration(final_path) if has_ffmpeg else 0
                size_kb = final_path.stat().st_size / 1024

                track_info["status"] = "success"
                track_info["filename"] = final_name
                track_info["duration_sec"] = round(dur, 1)
                track_info["size_kb"] = round(size_kb)
                track_info["path"] = str(final_path)

                event_bus.publish("track_complete", {
                    "concept_idx": concept_idx,
                    "track_number": num,
                    "title_ko": title_ko,
                    "status": "success",
                    "duration_sec": round(dur, 1),
                    "size_kb": round(size_kb),
                }, job.id)
                self._log(job, f"  [{num:02d}] ✓ {final_name} ({dur:.0f}초, {size_kb:.0f}KB)")

                # 비용 업데이트 이벤트
                cost = cost_tracker.get_job_cost(job.id)
                event_bus.publish("cost_update", cost, job.id)
            else:
                track_info["status"] = "failed"
                event_bus.publish("track_failed", {
                    "concept_idx": concept_idx,
                    "track_number": num,
                    "title_ko": title_ko,
                }, job.id)
                self._log(job, f"  [{num:02d}] ✗ 실패")

            if i < len(tracks) - 1:
                time.sleep(BETWEEN_TRACKS_DELAY)

    def retry_track(self, job_id: str, track_number: int) -> bool:
        """실패한 트랙 재시도"""
        job = self._jobs.get(job_id)
        if not job or not job.output_dir:
            return False

        track = None
        for t in job.tracks:
            if t.get("track_number") == track_number and t.get("status") == "failed":
                track = t
                break
        if not track:
            return False

        prompt = track.get("lyria_prompt", "")
        if not prompt:
            return False

        # 백그라운드에서 재시도
        self._executor.submit(self._retry_single_track, job, track, prompt)
        return True

    def _retry_single_track(self, job: Job, track_info: dict, prompt: str):
        """단일 트랙 재시도 실행"""
        num = track_info["track_number"]
        title_en = track_info.get("title_en", f"track_{num:02d}")
        title_ko = track_info.get("title_ko", f"트랙 {num}")
        playlist_dir = Path(job.output_dir)

        track_info["status"] = "generating"
        self._log(job, f"  [{num:02d}] 재시도 중: {title_ko}...")
        event_bus.publish("track_progress", {
            "track_number": num, "title_ko": title_ko, "status": "generating",
        }, job.id)

        raw_path = playlist_dir / f"_raw_{num:02d}_{title_en}"
        audio = generate_one_track(prompt, raw_path, use_pro=True)

        if audio and audio.exists():
            cost_tracker.add_lyria(job.id)
            final_name = f"{num:02d}_{title_en}.mp3"
            final_path = playlist_dir / final_name

            has_ffmpeg = True
            try:
                import subprocess
                subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
            except Exception:
                has_ffmpeg = False

            if has_ffmpeg:
                final_path = post_process_audio(audio, final_path)
                if audio != final_path and audio.exists():
                    try:
                        audio.unlink()
                    except Exception:
                        pass
            else:
                try:
                    audio.rename(final_path)
                except Exception:
                    final_path = audio

            dur = get_audio_duration(final_path) if has_ffmpeg else 0
            size_kb = final_path.stat().st_size / 1024

            track_info["status"] = "success"
            track_info["filename"] = final_name
            track_info["duration_sec"] = round(dur, 1)
            track_info["size_kb"] = round(size_kb)
            track_info["path"] = str(final_path)

            event_bus.publish("track_complete", {
                "track_number": num, "title_ko": title_ko, "status": "success",
            }, job.id)
            self._log(job, f"  [{num:02d}] ✓ 재시도 성공: {final_name}")
            cost = cost_tracker.get_job_cost(job.id)
            event_bus.publish("cost_update", cost, job.id)
        else:
            track_info["status"] = "failed"
            event_bus.publish("track_failed", {"track_number": num, "title_ko": title_ko}, job.id)
            self._log(job, f"  [{num:02d}] ✗ 재시도 실패")

        self._save_to_disk()


job_manager = JobManager()
