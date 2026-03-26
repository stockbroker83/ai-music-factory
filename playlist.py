#!/usr/bin/env python3
"""
 Playlist Factory v2 — 자율 트렌드 리서치 + 바이럴 컨셉 AI 음원 공장
========================================================================

Step 0. 트렌드 리서치 (웹 검색: YouTube 인기 플리 + Spotify 인기 플레이리스트)
Step 0.5. Opus 4.6 바이럴 컨셉 업그레이더 (트렌드 분석 → 미래 바이럴 예측 → 컨셉 설계)
Step 1. Opus 4.6 트랙 설계 (20곡 프롬프트 목록)
Step 2. Lyria 3 Pro 음악 생성
Step 3. 오디오 후처리 + 폴더 정리

사용법:
  python playlist.py --auto                        # 풀 자동 (트렌드→컨셉→생성)
  python playlist.py --auto --count 10             # 풀 자동 10곡
  python playlist.py --auto --concepts 3           # 3개 컨셉 자동 생성
  python playlist.py --concept "비오는 날 카페"     # 수동 컨셉 (리서치 건너뜀)
  python playlist.py --preset cafe_morning          # 프리셋 사용
  python playlist.py --research-only               # 트렌드 분석만 (음악 생성 X)
  python playlist.py --dry-run --auto              # 컨셉만 확인 (음악 생성 X)
  python playlist.py --batch concepts.json
  python playlist.py                                # 대화형 모드

필요 API 키 (.env):
  ANTHROPIC_API_KEY=sk-ant-...    # Opus 4.6 (리서치 + 설계)
  GEMINI_API_KEY=...               # Lyria 3 Pro (음악 생성)
"""

import os
import sys
import re
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
DEFAULT_OUTPUT_DIR = os.getenv("PLAYLIST_OUTPUT_DIR", str(Path.home() / "music" / "AI_Playlist"))

DEFAULT_COUNT = 20
MAX_RETRY = 3
RETRY_DELAY = 5
BETWEEN_TRACKS_DELAY = 10
LYRIA_COST_PER_TRACK = 0.08


# ─────────────────────────────────────────────
# 내장 프리셋 (8종)
# ─────────────────────────────────────────────
PRESETS = {
    "cafe_morning": {
        "name": "아침 카페 어쿠스틱",
        "description": "따뜻한 라떼와 함께 듣는 부드러운 어쿠스틱",
        "mood": "warm, gentle, cozy",
        "genre": "acoustic cafe, bossa nova, soft jazz",
        "instruments": "acoustic guitar, piano, soft brushed drums, upright bass",
        "vocal": "no vocals, instrumental only",
        "tempo": "70-95 BPM",
    },
    "cafe_afternoon": {
        "name": "오후 카페 재즈",
        "description": "나른한 오후, 커피 한 잔과 함께",
        "mood": "mellow, sophisticated, laid-back",
        "genre": "smooth jazz, lounge, cafe jazz",
        "instruments": "piano trio, saxophone, vibraphone, brushed drums",
        "vocal": "occasional light hum, mostly instrumental",
        "tempo": "80-110 BPM",
    },
    "rainy_day": {
        "name": "비오는 날 감성",
        "description": "잔잔하고 감성적인 피아노 중심",
        "mood": "melancholic, reflective, peaceful",
        "genre": "emotional piano, ambient, soft pop ballad",
        "instruments": "piano, soft strings, rain ambience, synth pad",
        "vocal": "soft breathy female vocal or instrumental",
        "tempo": "60-85 BPM",
    },
    "night_drive": {
        "name": "밤 드라이브 시티팝",
        "description": "도시의 밤거리를 달리며 듣는 레트로 감성",
        "mood": "nostalgic, dreamy, urban night",
        "genre": "city pop, synthwave, retrowave",
        "instruments": "analog synth, electric guitar, slap bass, drum machine",
        "vocal": "smooth vocal, city pop style",
        "tempo": "100-120 BPM",
    },
    "dawn_ballad": {
        "name": "새벽 감성 발라드",
        "description": "새벽 3시, 감성 폭발 한국 발라드",
        "mood": "emotional, intimate, vulnerable, longing",
        "genre": "Korean ballad, emotional pop, piano ballad",
        "instruments": "piano, strings, acoustic guitar, cello",
        "vocal": "emotional Korean vocal, breathy and intimate",
        "tempo": "65-80 BPM",
    },
    "study_lofi": {
        "name": "공부할 때 Lo-fi",
        "description": "집중할 때 틀어두는 lo-fi 비트",
        "mood": "chill, focused, calm",
        "genre": "lo-fi hip hop, chillhop, study beats",
        "instruments": "lo-fi piano, vinyl crackle, mellow drums",
        "vocal": "no vocals, instrumental",
        "tempo": "75-90 BPM",
    },
    "healing_ambient": {
        "name": "힐링 앰비언트",
        "description": "명상, 수면 전 힐링 사운드스케이프",
        "mood": "serene, spacious, healing, meditative",
        "genre": "ambient, new age, meditation",
        "instruments": "synth pads, crystal bowls, soft piano, nature sounds",
        "vocal": "no vocals",
        "tempo": "50-70 BPM",
    },
    "indie_acoustic": {
        "name": "인디 어쿠스틱 감성",
        "description": "봄날 공원 산책길에 듣는 따뜻한 인디",
        "mood": "warm, hopeful, youthful, breezy",
        "genre": "indie folk, indie acoustic, soft pop",
        "instruments": "acoustic guitar, ukulele, light percussion, harmonica",
        "vocal": "warm casual vocal",
        "tempo": "90-115 BPM",
    },
}


# ─────────────────────────────────────────────
# 유틸리티
# ─────────────────────────────────────────────
def safe_filename(text: str, max_len: int = 40) -> str:
    safe = re.sub(r'[^\w가-힣]', '_', text)
    safe = re.sub(r'_+', '_', safe).strip('_')
    return safe[:max_len]


def retry_call(func, max_attempts=MAX_RETRY, base_delay=RETRY_DELAY):
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            if attempt == max_attempts:
                print(f"      ❌ {max_attempts}회 재시도 후 실패: {e}")
                return None
            delay = base_delay * (2 ** (attempt - 1))
            print(f"      ⚠️ 시도 {attempt}/{max_attempts} 실패: {e}")
            print(f"      ⏳ {delay}초 후 재시도...")
            time.sleep(delay)


def get_audio_duration(path: Path) -> float:
    try:
        cmd = ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
               "-of", "csv=p=0", str(path)]
        return float(subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip())
    except Exception:
        return 0.0


def post_process_audio(input_path: Path, output_path: Path) -> Path:
    """노멀라이즈 + 페이드 + 무음제거 + 320kbps MP3"""
    try:
        dur = get_audio_duration(input_path)
        fade_out = max(0, dur - 3)
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-af", (
                "silenceremove=start_periods=1:start_silence=0.3:start_threshold=-50dB,"
                "areverse,silenceremove=start_periods=1:start_silence=0.3:start_threshold=-50dB,areverse,"
                f"loudnorm=I=-14:TP=-1:LRA=11,afade=t=in:st=0:d=2,afade=t=out:st={fade_out}:d=3"
            ),
            "-c:a", "libmp3lame", "-b:a", "320k", "-ar", "48000",
            str(output_path)
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if r.returncode == 0 and output_path.exists():
            return output_path
    except Exception:
        pass
    # 폴백
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(input_path),
                        "-c:a", "libmp3lame", "-b:a", "320k", str(output_path)],
                       capture_output=True, timeout=60)
        if output_path.exists():
            return output_path
    except Exception:
        pass
    if input_path.suffix == ".mp3":
        shutil.copy2(str(input_path), str(output_path))
        return output_path
    return input_path


def check_deps():
    missing = []
    if not ANTHROPIC_API_KEY: missing.append("ANTHROPIC_API_KEY (.env)")
    if not GEMINI_API_KEY: missing.append("GEMINI_API_KEY (.env)")
    for mod, pip in [("anthropic", "anthropic"), ("google.genai", "google-genai")]:
        try: __import__(mod)
        except ImportError: missing.append(f"{pip} (pip install {pip})")
    if missing:
        print("❌ 누락:")
        for m in missing: print(f"   → {m}")
        sys.exit(1)
    has_ffmpeg = True
    try: subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except Exception:
        has_ffmpeg = False
        print("⚠️  ffmpeg 미설치 — 후처리 건너뜀")
    print("✅ 의존성 확인 완료")
    return has_ffmpeg


# ═════════════════════════════════════════════
# Step 0. 트렌드 리서치 엔진 (NEW)
# ═════════════════════════════════════════════
def research_trends() -> dict:
    """
    Anthropic API의 web_search 도구를 사용하여
    YouTube 인기 플리 + Spotify 인기 플레이리스트 트렌드를 수집합니다.

    Returns:
        {
            "youtube_trends": "...",    # YouTube 플리 채널 트렌드 원문
            "spotify_trends": "...",    # Spotify 인기 플레이리스트 트렌드 원문
            "raw_search_results": [...]
        }
    """
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    print(" Step 0: 트렌드 리서치 중...")
    print("    YouTube 인기 플레이리스트 분석...")
    print("    Spotify 인기 플레이리스트 분석...")

    research_prompt = """다음 두 가지를 웹에서 검색하고 상세히 정리해주세요:

1. **YouTube 한국 플레이리스트 채널 트렌드 (2025-2026)**
   - 최근 조회수가 높은 한국어 음악 플레이리스트 채널들
   - 어떤 컨셉/무드의 플리가 인기인지 (카페, 새벽, 비오는날, 드라이브 등)
   - 조회수 100만 이상 플리의 공통 특징
   - 제목 네이밍 패턴 (이모지, 키워드)
   - 최근 새롭게 뜨는 플리 트렌드

2. **Spotify/음원 플랫폼 인기 플레이리스트 트렌드 (글로벌 + 한국)**
   - 현재 인기 있는 무드/장르 플레이리스트
   - 계절별 트렌드 (봄/여름/가을/겨울)
   - 상황별 인기 카테고리 (공부, 운동, 수면, 카페, 드라이브 등)
   - 새롭게 성장하는 니치 장르

각 항목에 대해 구체적인 채널명, 플레이리스트명, 조회수 데이터가 있으면 포함해주세요.
가능한 한 최신 데이터를 기반으로 답변해주세요."""

    def _search():
        msg = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=4096,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
            }],
            messages=[{"role": "user", "content": research_prompt}]
        )

        # 텍스트 블록만 추출
        texts = []
        for block in msg.content:
            if hasattr(block, 'text'):
                texts.append(block.text)

        return "\n\n".join(texts)

    raw_result = retry_call(_search)

    if not raw_result:
        print("   ⚠️ 웹 검색 실패 — 내장 트렌드 데이터 사용")
        raw_result = _fallback_trends()

    print("   ✅ 트렌드 리서치 완료")

    return {
        "trend_data": raw_result,
        "researched_at": datetime.now().isoformat(),
    }


def _fallback_trends() -> str:
    """웹 검색 실패 시 내장 트렌드 데이터"""
    return """
[내장 트렌드 데이터 — 2025-2026 기준]

YouTube 플레이리스트 트렌드:
- "새벽감성" 키워드 플리: 지속 인기, 특히 한국 발라드 + 피아노 조합
- "카페 음악" 플리: 가장 안정적인 조회수, 재즈/보사노바/어쿠스틱
- "비오는 날" 플리: 계절 무관 상시 수요, ASMR 빗소리 + 피아노
- "밤 드라이브" 시티팝: MZ세대 중심 급성장, 레트로 무드
- "공부 음악" lo-fi: 장시간 재생 → 높은 시청시간
- 신규 트렌드: "출근길 모닝 플리", "퇴근 후 위로 플리", "혼술 감성"
- 제목 패턴: 이모지 + 상황 묘사 ("️ 비오는 날 창가에서 듣는 재즈 카페 플레이리스트")
- 조회수 100만+ 공통: 3시간+ 길이, 계절/날씨/상황 명시, 영상 비주얼 통일감

Spotify/음원 트렌드:
- 글로벌: Chill, Focus, Sleep 카테고리 지속 성장
- 한국: K-인디 어쿠스틱, 감성 R&B, 뉴에이지 피아노
- 니치 성장: Cottagecore 뮤직, Dark Academia 사운드트랙, Japandi 앰비언트
- 계절: 봄(어쿠스틱/인디팝), 여름(트로피컬/라틴), 가을(재즈/포크), 겨울(발라드/앰비언트)
"""


# ═════════════════════════════════════════════
# Step 0.5. Opus 바이럴 컨셉 업그레이더 (NEW)
# ═════════════════════════════════════════════
def opus_viral_concept_upgrade(
    trend_data: str,
    num_concepts: int = 1,
    user_hint: str = "",
) -> list[dict]:
    """
    트렌드 데이터를 분석하고, 가까운 미래에 바이럴 가능성이 높은
    플레이리스트 컨셉을 설계합니다.

    Opus 4.6의 역할:
    1. 트렌드 패턴 분석 (무엇이 왜 인기인지)
    2. 포화 영역 vs 블루오션 식별
    3. 계절/시기 적합성 판단
    4. 바이럴 가능한 제목 + 컨셉 설계
    5. 차별화 포인트 명시

    Returns: [{concept_name, concept_description, viral_reason,
               target_audience, title_suggestion, mood, genre,
               instruments, vocal, tempo, season_fit,
               differentiation}, ...]
    """
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    now = datetime.now()
    month = now.month
    seasons = {(3,4,5): "봄", (6,7,8): "여름", (9,10,11): "가을", (12,1,2): "겨울"}
    current_season = next(v for k, v in seasons.items() if month in k)

    user_hint_section = ""
    if user_hint:
        user_hint_section = f"""
사용자가 대략적으로 원하는 방향:
"{user_hint}"
이 방향성을 존중하되, 트렌드 분석을 기반으로 더 바이럴할 수 있도록 업그레이드하세요.
"""

    system_prompt = f"""당신은 YouTube 플레이리스트 채널 전문 프로듀서이자 트렌드 분석가입니다.
현재 날짜: {now.strftime('%Y년 %m월 %d일')}
현재 계절: {current_season}

당신의 임무:
1. 주어진 트렌드 데이터를 분석합니다
2. 현재 인기 있는 것 vs 아직 블루오션인 것을 구분합니다
3. 가까운 미래(1-3개월)에 바이럴 가능성이 높은 플리 컨셉을 설계합니다
4. 단순히 "인기 있는 걸 따라하기"가 아니라, 트렌드의 빈틈을 공략하는 전략적 컨셉입니다

바이럴 컨셉 설계 원칙:
- 검색량이 높은 키워드 + 아직 경쟁이 적은 조합
- 특정 상황/감정에 강하게 연결되는 구체적 시나리오
- {current_season}에 맞는 계절감 반영
- 기존 인기 컨셉의 하위 니치를 공략 (예: "카페 음악" → "비오는 주말 오후 북카페 재즈")
- YouTube 제목으로 바로 쓸 수 있는 클릭 유발 네이밍
{user_hint_section}
반드시 아래 JSON 배열로만 응답하세요 (다른 텍스트 없이):

[
  {{
    "concept_name": "컨셉 한줄 이름 (20자 이내)",
    "concept_description": "이 컨셉이 무엇인지 상세 설명 (50자)",
    "viral_reason": "왜 이것이 바이럴할 것인지 근거 (트렌드 데이터 기반)",
    "target_audience": "타겟 리스너 (구체적으로)",
    "title_suggestion": "YouTube 플리 제목 예시 (이모지 포함, 60자 이내)",
    "mood": "무드 키워드 3-5개",
    "genre": "장르 (구체적으로)",
    "instruments": "핵심 악기 구성",
    "vocal": "보컬 방향 (인스트루멘탈 / 여성보컬 / 등)",
    "tempo": "BPM 범위",
    "season_fit": "적합 계절/시기",
    "differentiation": "기존 경쟁 플리 대비 차별점"
  }}
]

{num_concepts}개의 컨셉을 만들어주세요. 각 컨셉은 서로 겹치지 않는 다른 영역이어야 합니다."""

    print(f"\n Step 0.5: Opus 4.6 바이럴 컨셉 업그레이드 중... ({num_concepts}개)")

    def _call():
        msg = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=4096,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"다음 트렌드 데이터를 분석하고 바이럴 컨셉을 설계해주세요:\n\n{trend_data}"
            }]
        )
        return msg.content[0].text.strip()

    raw = retry_call(_call)
    if not raw:
        print("   ⚠️ 컨셉 생성 실패 — 프리셋으로 폴백")
        return [{"concept_name": v["name"], **v} for v in list(PRESETS.values())[:num_concepts]]

    # JSON 파싱
    text = raw
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("["):
                text = part
                break

    try:
        concepts = json.loads(text)
    except json.JSONDecodeError:
        print("   ⚠️ JSON 파싱 실패 — 프리셋으로 폴백")
        return [{"concept_name": v["name"], **v} for v in list(PRESETS.values())[:num_concepts]]

    print(f"   ✅ {len(concepts)}개 바이럴 컨셉 생성 완료:\n")
    for i, c in enumerate(concepts, 1):
        print(f"   {'━' * 50}")
        print(f"    컨셉 {i}: {c.get('concept_name', 'N/A')}")
        print(f"    {c.get('concept_description', '')}")
        print(f"    바이럴 근거: {c.get('viral_reason', '')}")
        print(f"    타겟: {c.get('target_audience', '')}")
        print(f"    제목 예시: {c.get('title_suggestion', '')}")
        print(f"    장르: {c.get('genre', '')} | 템포: {c.get('tempo', '')}")
        print(f"   ✨ 차별점: {c.get('differentiation', '')}")

    return concepts


# ═════════════════════════════════════════════
# Step 1. Opus 트랙 설계
# ═════════════════════════════════════════════
def opus_design_playlist(concept_data: dict, count: int) -> list[dict]:
    """
    바이럴 컨셉 데이터를 기반으로 N곡의 Lyria 프롬프트 목록 생성.
    concept_data는 opus_viral_concept_upgrade()의 결과 또는 프리셋.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    # concept_data에서 정보 추출
    concept_name = concept_data.get("concept_name", concept_data.get("name", ""))
    mood = concept_data.get("mood", "")
    genre = concept_data.get("genre", "")
    instruments = concept_data.get("instruments", "")
    vocal = concept_data.get("vocal", "")
    tempo = concept_data.get("tempo", "")
    description = concept_data.get("concept_description", concept_data.get("description", ""))
    differentiation = concept_data.get("differentiation", "")

    system_prompt = f"""당신은 음악 플레이리스트 프로듀서입니다.
주어진 컨셉 정보를 기반으로 {count}곡의 완벽한 플레이리스트를 설계합니다.

컨셉 정보:
- 이름: {concept_name}
- 설명: {description}
- 무드: {mood}
- 장르: {genre}
- 악기: {instruments}
- 보컬: {vocal}
- 템포: {tempo}
- 차별점: {differentiation}

설계 원칙:
1. 첫 곡은 부드럽게 시작, 중반에 에너지 변화, 마지막은 차분하게 마무리
2. 같은 키/BPM이 3곡 연속 오지 않도록
3. 악기 조합을 곡마다 변주
4. 모든 lyria_prompt는 영어로, 120단어 이상 상세하게
5. 반드시 총 길이 3분(180초)으로 설계. 곡 구조에 시간 배분 명시 (예: [Intro 15s] → [Verse1 40s] → [Chorus 35s] → [Verse2 40s] → [Bridge 20s] → [Outro 30s] = 180s)
6. 프롬프트에 "Total duration: exactly 3 minutes (180 seconds)" 반드시 포함
7. 컨셉의 차별점을 각 곡에 반영

JSON 배열로만 응답 (다른 텍스트 없이):
[
  {{
    "track_number": 1,
    "title_en": "snake_case_english_filename",
    "title_ko": "한국어 곡 제목",
    "lyria_prompt": "Detailed Lyria 3 Pro prompt in English, 120+ words. MUST specify total duration of exactly 3 minutes (180 seconds) with time-stamped structure.",
    "mood_tag": "one_word_mood"
  }},
  ...총 {count}곡
]"""

    print(f"\n Step 1: Opus 4.6 — {count}곡 트랙 설계 중...")

    def _call():
        msg = client.messages.create(
            model="claude-opus-4-20250514",
            max_tokens=4096 if count <= 10 else 8000,
            system=system_prompt,
            messages=[{
                "role": "user",
                "content": f"'{concept_name}' 컨셉으로 {count}곡 플레이리스트를 설계해주세요."
            }]
        )
        return msg.content[0].text.strip()

    raw = retry_call(_call)
    if not raw:
        return _fallback_tracks(concept_name, count)

    text = raw
    if "```" in text:
        for part in text.split("```"):
            part = part.strip()
            if part.startswith("json"): part = part[4:]
            part = part.strip()
            if part.startswith("["): text = part; break

    try:
        tracks = json.loads(text)
    except json.JSONDecodeError:
        print("   ⚠️ JSON 파싱 실패 — 폴백 트랙 사용")
        return _fallback_tracks(concept_name, count)

    for i, t in enumerate(tracks):
        t["track_number"] = i + 1
        if not t.get("lyria_prompt"):
            t["lyria_prompt"] = f"A beautiful {concept_name} track, studio quality. Total duration: exactly 3 minutes (180 seconds). [Intro 15s] Soft opening. [Verse1 40s] Main melody. [Chorus 35s] Emotional peak. [Verse2 40s] Development. [Bridge 20s] Contrast. [Outro 30s] Gentle fade."
        if not t.get("title_en"):
            t["title_en"] = f"track_{i+1:02d}"
        if not t.get("title_ko"):
            t["title_ko"] = f"트랙 {i+1}"

    print(f"   ✅ {len(tracks)}곡 설계 완료")
    for t in tracks[:5]:
        print(f"   {t['track_number']:02d}. {t['title_ko']} ({t.get('mood_tag', '')})")
    if len(tracks) > 5:
        print(f"   ... 외 {len(tracks)-5}곡")

    return tracks


def _fallback_tracks(concept: str, count: int) -> list:
    moods = ["gentle", "warm", "reflective", "hopeful", "dreamy",
             "melancholic", "peaceful", "intimate", "nostalgic", "serene"]
    return [{
        "track_number": i + 1,
        "title_en": f"{moods[i % len(moods)]}_track_{i+1:02d}",
        "title_ko": f"{moods[i % len(moods)]} 트랙 {i+1}",
        "lyria_prompt": (
            f"A {moods[i % len(moods)]} instrumental track: {concept}. "
            f"Total duration: exactly 3 minutes (180 seconds). Studio quality, 48kHz stereo. "
            f"[Intro 15s] Soft opening with ambient pad. [Verse1 40s] Main melody introduction. "
            f"[Chorus 35s] Emotional peak with full arrangement. [Verse2 40s] Melodic development and variation. "
            f"[Bridge 20s] Contrasting section. [Outro 30s] Gentle fade out. "
            f"Piano, soft strings, acoustic guitar. 75 BPM, C major. No vocals."
        ),
        "mood_tag": moods[i % len(moods)],
    } for i in range(count)]


# ═════════════════════════════════════════════
# Step 2. Lyria 3 Pro 음악 생성
# ═════════════════════════════════════════════
def generate_one_track(prompt: str, output_path: Path, use_pro: bool = True) -> Optional[Path]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)
    model_id = "lyria-3-pro-preview" if use_pro else "lyria-3-clip-preview"

    def _gen():
        response = client.models.generate_content(
            model=model_id,
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["AUDIO"])
        )
        if getattr(response, 'candidates', None) and len(response.candidates) > 0:
            for part in response.candidates[0].content.parts:
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    mime = getattr(part.inline_data, 'mime_type', '')
                    if mime.startswith('audio/'):
                        ext = ".mp3" if "mpeg" in mime else ".wav"
                        final = output_path.with_suffix(ext)
                        with open(final, 'wb') as f:
                            f.write(part.inline_data.data)
                        return final
        raise RuntimeError("응답에 오디오 없음")

    result = retry_call(_gen)
    if result is None and use_pro:
        print("       Clip(30초)으로 폴백...")
        return generate_one_track(prompt, output_path, use_pro=False)
    return result


# ═════════════════════════════════════════════
# 메인 파이프라인
# ═════════════════════════════════════════════
def run_full_auto(
    count: int = DEFAULT_COUNT,
    num_concepts: int = 1,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    user_hint: str = "",
    dry_run: bool = False,
    has_ffmpeg: bool = True,
) -> list[dict]:
    """
    풀 자동 파이프라인:
    Step 0   → 트렌드 리서치 (웹 검색)
    Step 0.5 → 바이럴 컨셉 업그레이드 (Opus 분석)
    Step 1   → 트랙 설계 (곡별 프롬프트)
    Step 2   → Lyria 3 Pro 음악 생성
    Step 3   → 후처리 + 폴더 정리
    """
    all_results = []

    print("\n" + "═" * 60)
    print(" Playlist Factory v2 — 풀 자동 모드")
    print("═" * 60)

    # Step 0: 트렌드 리서치
    print(f"\n{'━' * 50}")
    trends = research_trends()

    # 트렌드 저장
    trend_file = Path(output_dir) / "_latest_trends.json"
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    with open(trend_file, "w", encoding="utf-8") as f:
        json.dump(trends, f, ensure_ascii=False, indent=2)

    # Step 0.5: 바이럴 컨셉 업그레이드
    print(f"\n{'━' * 50}")
    concepts = opus_viral_concept_upgrade(
        trend_data=trends["trend_data"],
        num_concepts=num_concepts,
        user_hint=user_hint,
    )

    if dry_run:
        print(f"\n⚡ DRY-RUN 완료!")
        print(f"   트렌드: {trend_file}")
        print(f"   컨셉 {len(concepts)}개 생성됨 (음악 생성은 건너뜀)")
        return concepts

    # 컨셉별 플레이리스트 생성
    for ci, concept in enumerate(concepts, 1):
        concept_name = concept.get("concept_name", f"concept_{ci}")

        print(f"\n{'═' * 60}")
        print(f" [{ci}/{len(concepts)}] 컨셉: {concept_name}")
        print(f"{'═' * 60}")

        result = create_playlist_from_concept(
            concept_data=concept,
            count=count,
            output_dir=output_dir,
            has_ffmpeg=has_ffmpeg,
        )
        all_results.append(result)

        if ci < len(concepts):
            print(f"\n⏳ 다음 컨셉까지 30초 대기...")
            time.sleep(30)

    # 최종 요약
    print(f"\n{'═' * 60}")
    print(f" 전체 완료! {len(concepts)}개 컨셉 × {count}곡")
    print(f"{'═' * 60}")
    for r in all_results:
        if r:
            print(f"    {r.get('folder', 'N/A')}: {r.get('success', 0)}곡 성공")
    print(f"    저장: {output_dir}")

    return all_results


def create_playlist_from_concept(
    concept_data: dict,
    count: int,
    output_dir: str,
    has_ffmpeg: bool = True,
) -> dict:
    """단일 컨셉으로 플레이리스트 생성 (Step 1~3)"""
    start_time = time.time()
    today = datetime.now().strftime("%Y%m%d")

    concept_name = concept_data.get("concept_name", concept_data.get("name", "unnamed"))
    folder_name = f"{today}_{safe_filename(concept_name)}"
    playlist_dir = Path(output_dir) / folder_name
    playlist_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n    폴더: {playlist_dir}")
    print(f"    예상: ${count * LYRIA_COST_PER_TRACK:.2f} (약 ₩{int(count * LYRIA_COST_PER_TRACK * 1350):,})")

    # Step 1: 트랙 설계
    tracks = opus_design_playlist(concept_data, count)

    # 설계 저장
    with open(playlist_dir / "_playlist_design.json", "w", encoding="utf-8") as f:
        json.dump({
            "concept": concept_data,
            "count": count,
            "created_at": datetime.now().isoformat(),
            "tracks": tracks,
        }, f, ensure_ascii=False, indent=2)

    # Step 2 + 3: 음악 생성 + 후처리
    print(f"\n Step 2+3: Lyria 3 Pro 생성 + 후처리 ({len(tracks)}곡)")
    print("━" * 50)

    results = []
    success = 0
    fail = 0

    for i, track in enumerate(tracks):
        num = track["track_number"]
        title_en = safe_filename(track.get("title_en", f"track_{num:02d}"), 30)
        title_ko = track.get("title_ko", f"트랙 {num}")

        print(f"\n   [{num:02d}/{len(tracks)}] {title_ko}")

        raw_path = playlist_dir / f"_raw_{num:02d}_{title_en}"
        audio = generate_one_track(track["lyria_prompt"], raw_path, use_pro=True)

        if audio and audio.exists():
            final_name = f"{num:02d}_{title_en}.mp3"
            final_path = playlist_dir / final_name

            if has_ffmpeg:
                final_path = post_process_audio(audio, final_path)
                if audio != final_path and audio.exists():
                    audio.unlink()
            else:
                audio.rename(final_path)

            dur = get_audio_duration(final_path) if has_ffmpeg else 0
            size_kb = final_path.stat().st_size / 1024
            print(f"      ✅ {final_name} ({dur:.0f}초, {size_kb:.0f}KB)")

            results.append({
                "track_number": num, "title_ko": title_ko,
                "filename": final_name, "duration_sec": round(dur, 1),
                "size_kb": round(size_kb), "status": "success",
            })
            success += 1
        else:
            print(f"      ❌ 실패")
            results.append({"track_number": num, "title_ko": title_ko, "status": "failed"})
            fail += 1

        if i < len(tracks) - 1:
            time.sleep(BETWEEN_TRACKS_DELAY)

    elapsed = time.time() - start_time
    total_dur = sum(r.get("duration_sec", 0) for r in results if r["status"] == "success")
    total_mb = sum(r.get("size_kb", 0) for r in results if r["status"] == "success") / 1024

    info = {
        "concept": concept_data,
        "folder": str(playlist_dir),
        "created_at": datetime.now().isoformat(),
        "success": success, "failed": fail,
        "total_duration_min": round(total_dur / 60, 1),
        "total_size_mb": round(total_mb, 1),
        "cost_usd": round(success * LYRIA_COST_PER_TRACK, 2),
        "elapsed_min": round(elapsed / 60, 1),
        "tracks": results,
    }

    with open(playlist_dir / "_playlist_info.json", "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(f"\n    {concept_name}: {success}곡 완료 ({total_dur/60:.1f}분, {total_mb:.1f}MB)")

    return info


# ═════════════════════════════════════════════
# CLI
# ═════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description=" Playlist Factory v2 — 트렌드 리서치 + 바이럴 컨셉 + AI 음원 공장",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python playlist.py --auto                              # 풀 자동 (1컨셉 20곡)
  python playlist.py --auto --concepts 3 --count 20      # 3컨셉 × 20곡
  python playlist.py --auto --hint "카페 감성"            # 방향 힌트 + 자동
  python playlist.py --concept "비오는 날 카페" --count 20 # 수동 컨셉
  python playlist.py --preset rainy_day                   # 프리셋
  python playlist.py --research-only                      # 트렌드 분석만
  python playlist.py --dry-run --auto --concepts 3        # 컨셉만 확인
  python playlist.py --list-presets
  python playlist.py                                      # 대화형 모드
        """
    )

    parser.add_argument("--auto", action="store_true", help="풀 자동 (트렌드→컨셉→생성)")
    parser.add_argument("--hint", type=str, default="", help="--auto 사용 시 방향 힌트")
    parser.add_argument("--concepts", type=int, default=1, help="--auto 시 컨셉 개수 (기본: 1)")
    parser.add_argument("--concept", "-c", type=str, help="수동 컨셉 지정")
    parser.add_argument("--preset", "-p", type=str, help="프리셋 이름")
    parser.add_argument("--count", "-n", type=int, default=DEFAULT_COUNT, help=f"곡 수 (기본: {DEFAULT_COUNT})")
    parser.add_argument("--output", "-o", type=str, default=DEFAULT_OUTPUT_DIR, help="저장 경로")
    parser.add_argument("--batch", "-b", type=str, help="배치 JSON")
    parser.add_argument("--dry-run", action="store_true", help="프롬프트/컨셉만 (음악 X)")
    parser.add_argument("--research-only", action="store_true", help="트렌드 분석만")
    parser.add_argument("--list-presets", action="store_true", help="프리셋 목록")
    parser.add_argument("--skip-check", action="store_true")

    args = parser.parse_args()

    # 프리셋 목록
    if args.list_presets:
        print("\n 내장 프리셋 (8종)")
        print("=" * 50)
        for k, v in PRESETS.items():
            print(f"\n   {k}: {v['name']}")
            print(f"     {v['description']}")
            print(f"     장르: {v['genre']}")
        return

    has_ffmpeg = True
    if not args.skip_check:
        has_ffmpeg = check_deps()

    # 트렌드 리서치만
    if args.research_only:
        trends = research_trends()
        out_file = Path(args.output) / "_latest_trends.json"
        Path(args.output).mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(trends, f, ensure_ascii=False, indent=2)

        # 컨셉 추천도 같이
        concepts = opus_viral_concept_upgrade(trends["trend_data"], num_concepts=5)
        rec_file = Path(args.output) / "_concept_recommendations.json"
        with open(rec_file, "w", encoding="utf-8") as f:
            json.dump(concepts, f, ensure_ascii=False, indent=2)

        print(f"\n 트렌드: {out_file}")
        print(f" 추천 컨셉: {rec_file}")
        return

    # 풀 자동 모드
    if args.auto:
        run_full_auto(
            count=args.count,
            num_concepts=args.concepts,
            output_dir=args.output,
            user_hint=args.hint,
            dry_run=args.dry_run,
            has_ffmpeg=has_ffmpeg,
        )
        return

    # 배치 모드
    if args.batch:
        with open(args.batch, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        for i, job in enumerate(jobs, 1):
            concept_name = job.get("concept", "")
            preset_name = job.get("preset")
            preset = PRESETS.get(preset_name) if preset_name else None
            count = job.get("count", DEFAULT_COUNT)

            if preset and not concept_name:
                concept_data = {**preset, "concept_name": preset["name"]}
            elif concept_name:
                concept_data = {"concept_name": concept_name, "description": concept_name}
            else:
                continue

            print(f"\n [{i}/{len(jobs)}] {concept_data['concept_name']}")
            create_playlist_from_concept(concept_data, count, args.output, has_ffmpeg)
            if i < len(jobs): time.sleep(30)
        return

    # 프리셋/수동 컨셉
    if args.preset:
        if args.preset not in PRESETS:
            print(f"❌ 알 수 없는 프리셋: {args.preset}")
            return
        preset = PRESETS[args.preset]
        concept_data = {**preset, "concept_name": preset["name"]}
        create_playlist_from_concept(concept_data, args.count, args.output, has_ffmpeg)
        return

    if args.concept:
        concept_data = {"concept_name": args.concept, "description": args.concept}
        create_playlist_from_concept(concept_data, args.count, args.output, has_ffmpeg)
        return

    # 대화형 모드
    print("\n Playlist Factory v2 — 대화형 모드")
    print("=" * 50)
    print("  1. auto  → 풀 자동 (트렌드 리서치 → 바이럴 컨셉 → 생성)")
    print("  2. 직접 컨셉 입력")
    print("  3. 프리셋 선택")
    print("  quit → 종료\n")

    while True:
        choice = input(" 선택 (auto / 컨셉 입력 / 프리셋번호) → ").strip()

        if choice.lower() in ("quit", "exit", "q"):
            break

        if choice.lower() == "auto":
            hint = input("    방향 힌트 (없으면 Enter) → ").strip()
            nc = input("    컨셉 개수 (기본 1) → ").strip()
            nc = int(nc) if nc.isdigit() else 1
            ct = input(f"    곡 수 (기본 {DEFAULT_COUNT}) → ").strip()
            ct = int(ct) if ct.isdigit() else DEFAULT_COUNT
            out = input(f"    저장 경로 (기본: {args.output}) → ").strip() or args.output

            run_full_auto(
                count=ct, num_concepts=nc, output_dir=out,
                user_hint=hint, has_ffmpeg=has_ffmpeg,
            )
            continue

        if choice.isdigit():
            idx = int(choice) - 1
            keys = list(PRESETS.keys())
            if 0 <= idx < len(keys):
                preset = PRESETS[keys[idx]]
                concept_data = {**preset, "concept_name": preset["name"]}
                ct = input(f"    곡 수 (기본 {DEFAULT_COUNT}) → ").strip()
                ct = int(ct) if ct.isdigit() else DEFAULT_COUNT
                out = input(f"    저장 경로 → ").strip() or args.output
                create_playlist_from_concept(concept_data, ct, out, has_ffmpeg)
            else:
                print("   프리셋 목록:")
                for i, (k, v) in enumerate(PRESETS.items(), 1):
                    print(f"   {i}. {v['name']}")
            continue

        if choice:
            concept_data = {"concept_name": choice, "description": choice}
            ct = input(f"    곡 수 (기본 {DEFAULT_COUNT}) → ").strip()
            ct = int(ct) if ct.isdigit() else DEFAULT_COUNT
            out = input(f"    저장 경로 → ").strip() or args.output
            create_playlist_from_concept(concept_data, ct, out, has_ffmpeg)


if __name__ == "__main__":
    main()
