#!/usr/bin/env python3
"""
 AI Music Factory Pipeline
=============================
Opus 4.6 오케스트레이터 → Lyria 3 Pro 음악 생성 → FFmpeg 비주얼 영상 → YouTube 자동 업로드

사용법:
  python pipeline.py "한국 발라드 느낌의 감성적인 피아노 곡"
  python pipeline.py --theme "lo-fi chill" --mood "relaxing study"
  python pipeline.py --batch themes.json          # 배치 모드 (여러 곡)
  python pipeline.py --interactive                  # 대화형 모드

필요 API 키 (.env):
  GEMINI_API_KEY=...                  # Gemini (오케스트레이터) + Lyria 3 Pro (음악 생성)

필요 OAuth (.env 또는 파일):
  YouTube: client_secrets.json        # Google Cloud Console OAuth 2.0
"""

import os
import sys
import json
import time
import glob
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("⚠️  python-dotenv 미설치. pip install python-dotenv")

# ─────────────────────────────────────────────
# 1. 설정 및 상수
# ─────────────────────────────────────────────
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# YouTube 기본 설정
YT_CATEGORY_ID = "10"  # Music
YT_PRIVACY = os.getenv("YT_PRIVACY", "unlisted")  # public / unlisted / private
YT_DEFAULT_TAGS = ["AI Music", "Lyria 3 Pro", "AI Generated"]


def check_dependencies():
    """필수 의존성 확인"""
    missing = []

    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY (.env)")

    # FFmpeg 확인
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        missing.append("ffmpeg (터미널: sudo apt install ffmpeg 또는 winget install ffmpeg)")

    # Python 패키지 확인
    required_packages = {
        "google.genai": "google-genai",
        "google_auth_oauthlib": "google-auth-oauthlib",
        "googleapiclient": "google-api-python-client",
    }

    for module, pip_name in required_packages.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(f"{pip_name} (pip install {pip_name})")

    if missing:
        print("❌ 누락된 의존성:")
        for m in missing:
            print(f"   → {m}")
        sys.exit(1)

    print("✅ 모든 의존성 확인 완료")


# ─────────────────────────────────────────────
# 2. Opus 4.6 오케스트레이터 (핵심 두뇌)
# ─────────────────────────────────────────────
def opus_orchestrate(user_input: str) -> dict:
    """
    Gemini가 사용자 입력을 분석하여 전체 파이프라인 지시서를 생성합니다.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt_text = f"""당신은 AI 음악 프로덕션 총괄 프로듀서입니다.
사용자의 음악 요청을 받아 완전한 프로덕션 지시서를 JSON으로 생성합니다.

반드시 아래 JSON 형식으로만 응답하세요 (다른 텍스트 없이 순수 JSON만):

{{
  "music_prompt": "Lyria 3 Pro에 보낼 상세 영문 프롬프트. 반드시 총 길이 3분(180초)으로 설계. 장르, 템포(BPM), 무드, 악기 구성, 보컬 스타일, 가사 방향, 시간 배분이 포함된 곡 구조([Intro 15s]→[Verse1 40s]→[Chorus 35s]→[Verse2 40s]→[Bridge 20s]→[Outro 30s] = 180s)를 반드시 포함. 프롬프트에 'Total duration: exactly 3 minutes (180 seconds)' 명시. 최소 100단어.",
  "title_ko": "YouTube 제목 (한국어, 50자 이내, 클릭을 유도하는)",
  "title_en": "YouTube English subtitle",
  "description": "YouTube 설명문 (한국어 200자 + 영어 100단어 + 해시태그 5개)",
  "tags": ["태그1", "태그2", "...최소 10개"],
  "visual_style": {{
    "color_primary": "#hex색상",
    "color_secondary": "#hex색상",
    "color_accent": "#hex색상",
    "animation_type": "waveform|particles|spectrum|pulse 중 택1",
    "mood_keyword": "분위기를 한단어로"
  }},
  "filename_base": "영문_snake_case_파일명"
}}

프롬프트 작성 규칙:
1. music_prompt는 반드시 영어로, Lyria 3 Pro가 이해하는 형식으로 작성
2. 반드시 총 길이 3분(180초)으로 설계. 프롬프트 첫 줄에 "Total duration: exactly 3 minutes (180 seconds)" 명시
3. 곡 구조에 시간 배분 필수 (예: [Intro 15s] Soft piano... [Verse1 40s] ... 합계 = 180s)
4. 보컬이 있다면 성별, 톤, 언어를 명시
5. 가사 내용의 방향성 포함
6. 상업적 품질을 목표로 상세하게 기술

다음 요청으로 완전한 프로덕션 지시서를 만들어주세요:

{user_input}"""

    print(" Gemini 오케스트레이터 가동 중...")

    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt_text,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            ),
        )
        response_text = response.text.strip()
    except Exception as e:
        print(f"⚠️  API 호출 실패: {e}")
        response_text = ""

    # JSON 파싱 (코드블록 제거)
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
    response_text = response_text.strip().rstrip("```")

    try:
        result = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        print(f"⚠️  JSON 파싱 실패 — 폴백 사용")
        result = {
            "music_prompt": f"Total duration: exactly 3 minutes (180 seconds). {user_input}. [Intro 15s] Soft opening. [Verse1 40s] Main theme. [Chorus 35s] Emotional peak. [Verse2 40s] Development. [Bridge 20s] Contrast. [Outro 30s] Gentle fade.",
            "title_ko": f"AI 음악 - {user_input[:30]}",
            "title_en": "AI Generated Music",
            "description": f"AI가 생성한 음악입니다.\n\n{user_input}",
            "tags": YT_DEFAULT_TAGS,
            "visual_style": {
                "color_primary": "#1a1a2e",
                "color_secondary": "#16213e",
                "color_accent": "#e94560",
                "animation_type": "waveform",
                "mood_keyword": "cinematic"
            },
            "filename_base": f"ai_music_{int(time.time())}"
        }

    print(f"✅ 프로덕션 지시서 생성 완료")
    print(f"    곡 제목: {result.get('title_ko', 'N/A')}")
    print(f"    비주얼: {result.get('visual_style', {}).get('animation_type', 'waveform')}")

    return result


# ─────────────────────────────────────────────
# 3. Lyria 3 Pro 음악 생성
# ─────────────────────────────────────────────
def generate_music(prompt: str, output_path: Path) -> Path:
    """
    Lyria 3 Pro로 최대 3분 길이의 고품질 음원을 생성합니다.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=GEMINI_API_KEY)

    print(" Lyria 3 Pro 음악 생성 중... (1~3분 소요)")
    print(f"   프롬프트: {prompt[:100]}...")

    try:
        response = client.models.generate_content(
            model="lyria-3-pro-preview",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"]
            )
        )

        if getattr(response, 'candidates', None) and len(response.candidates) > 0:
            candidate = response.candidates[0]

            for part in candidate.content.parts:
                if hasattr(part, 'inline_data') and part.inline_data is not None:
                    mime = getattr(part.inline_data, 'mime_type', '')
                    if mime.startswith('audio/'):
                        # 확장자 결정
                        ext = ".mp3" if "mpeg" in mime else ".wav"
                        final_path = output_path.with_suffix(ext)

                        with open(final_path, 'wb') as f:
                            f.write(part.inline_data.data)

                        # 파일 크기 확인
                        size_mb = final_path.stat().st_size / (1024 * 1024)
                        print(f"✅ 음원 생성 완료: {final_path.name} ({size_mb:.1f}MB)")
                        return final_path

            print("❌ 응답에 오디오 데이터가 없습니다.")
        else:
            print("❌ Lyria 3 Pro 응답이 비어있습니다.")

    except Exception as e:
        print(f"❌ 음악 생성 오류: {e}")

    return None


# ─────────────────────────────────────────────
# 4. FFmpeg 비주얼 영상 생성
# ─────────────────────────────────────────────
def create_visual_video(
    audio_path: Path,
    output_video: Path,
    visual_style: dict,
    title_text: str = ""
) -> Path:
    """
    FFmpeg로 오디오 파형 시각화 + 파티클 배경 영상을 생성합니다.
    YouTube 업로드용 MP4 (1080x1920 세로 또는 1920x1080 가로)
    """

    color_primary = visual_style.get("color_primary", "#1a1a2e")
    color_accent = visual_style.get("color_accent", "#e94560")
    animation_type = visual_style.get("animation_type", "waveform")

    # 오디오 길이 확인
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(audio_path)
    ]
    try:
        duration = float(subprocess.check_output(probe_cmd).decode().strip())
    except Exception:
        duration = 180  # 기본 3분

    print(f" 비주얼 영상 생성 중... ({duration:.0f}초, 스타일: {animation_type})")

    # hex → FFmpeg 색상 형식 변환
    def hex_to_ffmpeg(hex_color):
        hex_color = hex_color.lstrip('#')
        return f"0x{hex_color}"

    bg_color = hex_to_ffmpeg(color_primary)
    wave_color = hex_to_ffmpeg(color_accent)

    # 영상 해상도 (16:9 가로형 — YouTube 일반 영상)
    width, height = 1920, 1080

    # FFmpeg 필터: 오디오 시각화 (showwaves 또는 showspectrum)
    if animation_type == "spectrum":
        # 스펙트럼 시각화
        filter_complex = (
            f"[0:a]showspectrum=s={width}x{height}:mode=combined"
            f":color=intensity:scale=cbrt:fps=30"
            f":win_func=hanning[v]"
        )
    elif animation_type == "particles":
        # 파형 + 그라데이션 배경
        filter_complex = (
            f"[0:a]showwaves=s={width}x{height//2}:mode=cline"
            f":colors={wave_color}:rate=30[waves];"
            f"color=c={bg_color}:s={width}x{height}:d={duration}:rate=30[bg];"
            f"[bg][waves]overlay=0:(H-h)/2:format=auto[v]"
        )
    elif animation_type == "pulse":
        # 볼륨 미터 스타일
        filter_complex = (
            f"[0:a]avectorscope=s={width}x{height}:mode=lissajous_xy"
            f":draw=dot:zoom=1.5:rate=30[v]"
        )
    else:
        # 기본 waveform
        filter_complex = (
            f"[0:a]showwaves=s={width}x{height}:mode=p2p"
            f":colors={wave_color}|white:rate=30:split_channels=0[waves];"
            f"color=c={bg_color}:s={width}x{height}:d={duration}:rate=30[bg];"
            f"[bg][waves]overlay=0:0:format=auto[v]"
        )

    # 제목 텍스트 오버레이 (있는 경우)
    if title_text:
        # 특수문자 이스케이프
        safe_title = title_text.replace("'", "'\\''").replace(":", "\\:")
        filter_complex += (
            f";[v]drawtext=text='{safe_title}'"
            f":fontsize=48:fontcolor=white"
            f":x=(w-text_w)/2:y=h-80"
            f":borderw=2:bordercolor=black[vout]"
        )
        map_label = "[vout]"
    else:
        map_label = "[v]"

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-filter_complex", filter_complex,
        "-map", map_label,
        "-map", "0:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-shortest",
        str(output_video)
    ]

    try:
        result = subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10분 타임아웃
        )

        if result.returncode == 0:
            size_mb = output_video.stat().st_size / (1024 * 1024)
            print(f"✅ 영상 생성 완료: {output_video.name} ({size_mb:.1f}MB)")
            return output_video
        else:
            print(f"❌ FFmpeg 오류:\n{result.stderr[-500:]}")

            # 폴백: 단순한 필터로 재시도
            print(" 단순 모드로 재시도...")
            simple_cmd = [
                "ffmpeg", "-y",
                "-i", str(audio_path),
                "-filter_complex",
                f"[0:a]showwaves=s={width}x{height}:mode=line:rate=30[v]",
                "-map", "[v]", "-map", "0:a",
                "-c:v", "libx264", "-preset", "fast", "-crf", "28",
                "-c:a", "aac", "-b:a", "192k",
                "-pix_fmt", "yuv420p", "-shortest",
                str(output_video)
            ]
            subprocess.run(simple_cmd, capture_output=True, timeout=600)
            if output_video.exists():
                print(f"✅ 영상 생성 완료 (단순 모드): {output_video.name}")
                return output_video

    except subprocess.TimeoutExpired:
        print("❌ 영상 생성 시간 초과 (10분)")
    except Exception as e:
        print(f"❌ 영상 생성 오류: {e}")

    return None


# ─────────────────────────────────────────────
# 5. YouTube 자동 업로드
# ─────────────────────────────────────────────
def upload_to_youtube(
    video_path: Path,
    title: str,
    description: str,
    tags: list,
    category_id: str = YT_CATEGORY_ID,
    privacy: str = YT_PRIVACY
) -> str:
    """
    YouTube Data API v3로 영상을 업로드합니다.
    최초 실행 시 OAuth 브라우저 인증이 필요합니다 (이후 토큰 자동 갱신).

    Returns:
        업로드된 영상의 video_id 또는 None
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    TOKEN_FILE = "youtube_token.json"
    CLIENT_SECRETS = "client_secrets.json"

    # --- 인증 ---
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print(" YouTube 토큰 갱신 중...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRETS):
                print("❌ client_secrets.json 파일이 없습니다!")
                print("   → Google Cloud Console에서 OAuth 2.0 Client ID를 만들고")
                print("   → JSON 다운로드 후 이 폴더에 client_secrets.json으로 저장하세요.")
                print("   → https://console.cloud.google.com/apis/credentials")
                return None

            print(" 브라우저에서 YouTube 계정 인증을 진행하세요...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS, SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=True)

        # 토큰 저장
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print("✅ YouTube 인증 완료 (토큰 저장됨)")

    # --- 업로드 ---
    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": title[:100],  # YouTube 제한
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": category_id,
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        }
    }

    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=10 * 1024 * 1024  # 10MB 청크
    )

    print(f" YouTube 업로드 중... ({video_path.name})")

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"   진행: {pct}%", end="\r")

        video_id = response["id"]
        video_url = f"https://youtu.be/{video_id}"

        print(f"\n✅ YouTube 업로드 완료!")
        print(f"    {video_url}")
        print(f"    공개 상태: {privacy}")

        return video_id

    except Exception as e:
        print(f"❌ YouTube 업로드 오류: {e}")
        return None


# ─────────────────────────────────────────────
# 6. 전체 파이프라인 실행
# ─────────────────────────────────────────────
def run_pipeline(user_input: str, auto_upload: bool = True):
    """
    전체 파이프라인을 순차 실행합니다.

    1. Opus 4.6 → 프로덕션 지시서 생성
    2. Lyria 3 Pro → 음원 생성
    3. FFmpeg → 비주얼 영상 생성
    4. YouTube → 자동 업로드
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("\n" + "=" * 60)
    print(" AI Music Factory Pipeline 시작")
    print("=" * 60)
    start_time = time.time()

    # Step 1: Opus 오케스트레이션
    print("\n [Step 1/4] Opus 4.6 프로덕션 지시서 생성")
    print("-" * 40)
    production = opus_orchestrate(user_input)

    # 지시서 저장
    filename_base = production.get("filename_base", f"track_{timestamp}")
    prod_file = OUTPUT_DIR / f"{filename_base}_production.json"
    with open(prod_file, "w", encoding="utf-8") as f:
        json.dump(production, f, ensure_ascii=False, indent=2)

    # Step 2: 음악 생성
    print(f"\n [Step 2/4] Lyria 3 Pro 음악 생성")
    print("-" * 40)
    audio_path = OUTPUT_DIR / f"{filename_base}_audio"
    audio_path = generate_music(production["music_prompt"], audio_path)

    if not audio_path:
        print("❌ 파이프라인 중단: 음악 생성 실패")
        return None

    # Step 3: 비주얼 영상 생성
    print(f"\n [Step 3/4] 비주얼 영상 렌더링")
    print("-" * 40)
    video_path = OUTPUT_DIR / f"{filename_base}_video.mp4"
    video_path = create_visual_video(
        audio_path=audio_path,
        output_video=video_path,
        visual_style=production.get("visual_style", {}),
        title_text=production.get("title_ko", "")
    )

    if not video_path:
        print("⚠️  영상 생성 실패 — 오디오만 업로드 가능")
        # 오디오를 영상으로 변환 (정적 이미지 + 오디오)
        video_path = OUTPUT_DIR / f"{filename_base}_video.mp4"
        fallback_cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c=0x1a1a2e:s=1920x1080:d=1",
            "-i", str(audio_path),
            "-c:v", "libx264", "-tune", "stillimage",
            "-c:a", "aac", "-b:a", "192k",
            "-pix_fmt", "yuv420p", "-shortest",
            str(video_path)
        ]
        subprocess.run(fallback_cmd, capture_output=True)
        if not video_path.exists():
            print("❌ 파이프라인 중단: 영상 변환도 실패")
            return None

    # Step 4: YouTube 업로드
    if auto_upload:
        print(f"\n [Step 4/4] YouTube 업로드")
        print("-" * 40)

        yt_title = production.get("title_ko", f"AI Music - {filename_base}")
        yt_desc = production.get("description", "AI generated music by Lyria 3 Pro")
        yt_tags = production.get("tags", YT_DEFAULT_TAGS)

        video_id = upload_to_youtube(
            video_path=video_path,
            title=yt_title,
            description=yt_desc,
            tags=yt_tags
        )
    else:
        print(f"\n⏭️  [Step 4/4] 업로드 건너뜀 (--no-upload)")
        video_id = None

    # 결과 요약
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print(" 파이프라인 완료!")
    print("=" * 60)
    print(f"   ⏱️  총 소요 시간: {elapsed:.0f}초 ({elapsed/60:.1f}분)")
    print(f"    음원: {audio_path}")
    print(f"    영상: {video_path}")
    if video_id:
        print(f"    YouTube: https://youtu.be/{video_id}")
    print(f"    지시서: {prod_file}")

    return {
        "audio": str(audio_path),
        "video": str(video_path),
        "production": production,
        "video_id": video_id,
        "elapsed_seconds": elapsed
    }


def run_batch(batch_file: str):
    """
    JSON 배치 파일에서 여러 곡을 순차 생성합니다.

    배치 파일 형식:
    [
      {"prompt": "lo-fi chill beats for studying"},
      {"prompt": "epic orchestral cinematic trailer"},
      ...
    ]
    """
    with open(batch_file, "r", encoding="utf-8") as f:
        tasks = json.load(f)

    print(f" 배치 모드: {len(tasks)}곡 처리 예정\n")

    results = []
    for i, task in enumerate(tasks, 1):
        print(f"\n{'='*60}")
        print(f" [{i}/{len(tasks)}] 처리 중...")
        print(f"{'='*60}")

        prompt = task.get("prompt", "")
        if not prompt:
            print(f"⚠️  빈 프롬프트, 건너뜀")
            continue

        result = run_pipeline(prompt, auto_upload=True)
        results.append(result)

        # API 부하 방지를 위한 딜레이
        if i < len(tasks):
            delay = 30
            print(f"\n⏳ 다음 곡까지 {delay}초 대기...")
            time.sleep(delay)

    # 최종 리포트
    print(f"\n{'='*60}")
    print(f" 배치 처리 완료: {len(results)}곡")
    print(f"{'='*60}")

    for i, r in enumerate(results, 1):
        if r:
            title = r["production"].get("title_ko", "N/A")
            vid = r.get("video_id", "업로드 안됨")
            print(f"   {i}. {title} → {vid}")


# ─────────────────────────────────────────────
# 7. CLI 엔트리포인트
# ─────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description=" AI Music Factory — Opus 4.6 + Lyria 3 Pro + YouTube 자동 업로드",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python pipeline.py "감성적인 한국 발라드"
  python pipeline.py --theme "lo-fi" --mood "chill study"
  python pipeline.py --batch themes.json
  python pipeline.py --no-upload "epic trailer music"
  python pipeline.py --privacy public "upbeat K-pop dance track"
        """
    )

    parser.add_argument("prompt", nargs="?", default=None,
                       help="음악 프롬프트 (자유 형식)")
    parser.add_argument("--theme", type=str, default=None,
                       help="음악 장르/테마")
    parser.add_argument("--mood", type=str, default=None,
                       help="분위기/무드")
    parser.add_argument("--batch", type=str, default=None,
                       help="배치 모드: JSON 파일 경로")
    parser.add_argument("--no-upload", action="store_true",
                       help="YouTube 업로드 건너뛰기")
    parser.add_argument("--privacy", type=str, default=YT_PRIVACY,
                       choices=["public", "unlisted", "private"],
                       help="YouTube 공개 상태 (기본: unlisted)")
    parser.add_argument("--interactive", action="store_true",
                       help="대화형 모드")
    parser.add_argument("--skip-check", action="store_true",
                       help="의존성 확인 건너뛰기")

    args = parser.parse_args()

    # 글로벌 설정 반영
    global YT_PRIVACY
    YT_PRIVACY = args.privacy

    if not args.skip_check:
        check_dependencies()

    # 배치 모드
    if args.batch:
        run_batch(args.batch)
        return

    # 대화형 모드
    if args.interactive:
        print("\n AI Music Factory — 대화형 모드")
        print("   'quit' 입력 시 종료\n")
        while True:
            user_input = input(" 어떤 음악을 만들까요? → ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                print(" 종료합니다.")
                break
            if user_input:
                run_pipeline(user_input, auto_upload=not args.no_upload)
        return

    # 단일 실행 모드
    prompt_parts = []
    if args.prompt:
        prompt_parts.append(args.prompt)
    if args.theme:
        prompt_parts.append(f"장르/테마: {args.theme}")
    if args.mood:
        prompt_parts.append(f"분위기: {args.mood}")

    if not prompt_parts:
        parser.print_help()
        print("\n 예시: python pipeline.py \"감성적인 피아노 발라드\"")
        return

    user_input = " | ".join(prompt_parts)
    run_pipeline(user_input, auto_upload=not args.no_upload)


if __name__ == "__main__":
    main()
