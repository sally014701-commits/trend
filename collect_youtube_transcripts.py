import argparse
import csv
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import imageio_ffmpeg
import yt_dlp
from google import genai


DEFAULT_INPUT = Path("data/processed/youtube_meta_raw.csv")
DEFAULT_OUTPUT = Path("data/processed/youtube_transcript_raw.csv")
DEFAULT_LOG = Path("data/processed/youtube_transcript_log.csv")
AUDIO_DIR = Path("data/raw/youtube_audio")
TXT_DIR = Path("data/raw/youtube_transcripts_txt")
ENV_PATH = Path(".env")
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_RETRY_COUNT = 5
GEMINI_RETRY_BASE_SECONDS = 10

OUTPUT_FIELDS = ["video_id", "transcript_raw", "transcript_cleaned", "source_type"]
LOG_FIELDS = [
    "processed_at",
    "video_id",
    "url",
    "audio_path",
    "audio_status",
    "transcription_status",
    "cleaning_status",
    "txt_status",
    "error",
]

TRANSCRIBE_PROMPT = "오디오 파일에서 한국어 스크립트를 만들어 주세요."
CLEAN_PROMPT = """다음 전사문은 줄바꿈이 일정하지 않아 문장 단위 분석이 어렵다.
내용을 삭제하거나 요약하지 말고, 원문의 내용을 최대한 그대로 유지하되 문장 단위로 줄바꿈되도록 정리해 줘.
책 제목, 저자명, 추천 이유, 독서 맥락은 절대 삭제하지 마.
하나의 책추천에서 다음 책추천으로 넘어갈 때는 한 줄을 비우고 줄바꿈해 줘.
인사말, 구독 요청, 광고성 멘트, 잡담도 자동 삭제하지 마.
별도의 화자 분리는 수행하지 마.

전사문:
{transcript}
"""


def load_env_file(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_gemini_api_key() -> str:
    load_env_file()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 .env에 없습니다.")
    return api_key


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="유튜브 오디오를 Gemini로 전사하고 문장 단위로 정리합니다.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="입력 CSV 경로")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="출력 CSV 경로")
    parser.add_argument("--test", action="store_true", help="앞의 1개 영상만 처리")
    parser.add_argument("--limit", type=int, default=None, help="앞의 N개 영상만 처리")
    parser.add_argument("--skip-existing", action="store_true", help="출력 CSV에 이미 있는 video_id는 건너뛰고 이어서 처리")
    return parser.parse_args()


def read_input_rows(path: Path, limit: int | None, test: bool) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    required = {"video_id", "url"}
    missing = required.difference(rows[0].keys() if rows else [])
    if missing:
        raise RuntimeError(f"입력 CSV에 필수 컬럼이 없습니다: {', '.join(sorted(missing))}")

    if test:
        return rows[:1]
    if limit is not None:
        return rows[: max(limit, 0)]
    return rows


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as csv_file:
        return list(csv.DictReader(csv_file))


def extract_audio(url: str, video_id: str) -> Path:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    output_path = AUDIO_DIR / f"{video_id}.mp3"
    if output_path.exists() and output_path.stat().st_size > 0:
        return output_path

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
    ydl_opts: dict[str, Any] = {
        "format": "bestaudio/best",
        "outtmpl": str(AUDIO_DIR / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "ffmpeg_location": ffmpeg_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(f"mp3 파일이 생성되지 않았습니다: {output_path}")
    return output_path


def wait_for_file_ready(client: genai.Client, uploaded_file: Any, timeout_seconds: int = 300) -> Any:
    name = uploaded_file.name
    deadline = time.time() + timeout_seconds
    current = uploaded_file

    while time.time() < deadline:
        state = getattr(current, "state", None)
        state_name = getattr(state, "name", str(state))
        if state_name in {"ACTIVE", "FileState.ACTIVE"}:
            return current
        if state_name in {"FAILED", "FileState.FAILED"}:
            raise RuntimeError(f"Gemini 파일 처리 실패: {name}")
        time.sleep(5)
        current = client.files.get(name=name)

    raise TimeoutError(f"Gemini 파일 처리 대기 시간이 초과되었습니다: {name}")


def response_text(response: Any) -> str:
    return (getattr(response, "text", "") or "").strip()


def is_retryable_gemini_error(exc: Exception) -> bool:
    message = str(exc)
    if "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in message:
        return False
    return any(code in message for code in ("429", "500", "502", "503", "504", "UNAVAILABLE", "RESOURCE_EXHAUSTED"))


def run_gemini_with_retry(action_name: str, fn: Callable[[], Any]) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, GEMINI_RETRY_COUNT + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt == GEMINI_RETRY_COUNT or not is_retryable_gemini_error(exc):
                raise
            wait_seconds = GEMINI_RETRY_BASE_SECONDS * attempt
            print(f"{action_name} 재시도 대기: {wait_seconds}초 ({attempt}/{GEMINI_RETRY_COUNT})")
            time.sleep(wait_seconds)
    raise last_error or RuntimeError(f"{action_name} 실패")


def transcribe_audio(client: genai.Client, audio_path: Path) -> str:
    uploaded = client.files.upload(file=audio_path)
    uploaded = wait_for_file_ready(client, uploaded)
    try:
        response = run_gemini_with_retry(
            "Gemini 전사",
            lambda: client.models.generate_content(
                model=MODEL_NAME,
                contents=[TRANSCRIBE_PROMPT, uploaded],
            ),
        )
        transcript = response_text(response)
        if not transcript:
            raise RuntimeError("Gemini 전사 결과가 비어 있습니다.")
        return transcript
    finally:
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass


def clean_transcript(client: genai.Client, transcript: str) -> str:
    response = run_gemini_with_retry(
        "Gemini 문장 정리",
        lambda: client.models.generate_content(
            model=MODEL_NAME,
            contents=CLEAN_PROMPT.format(transcript=transcript),
        ),
    )
    cleaned = response_text(response)
    if not cleaned:
        raise RuntimeError("Gemini 문장 정리 결과가 비어 있습니다.")
    return cleaned


def write_output(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_log(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=LOG_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def save_txt(video_id: str, transcript_cleaned: str) -> Path:
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    txt_path = TXT_DIR / f"{video_id}.txt"
    txt_path.write_text(transcript_cleaned, encoding="utf-8")
    return txt_path


def main() -> None:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    log_path = DEFAULT_LOG
    input_rows = read_input_rows(input_path, args.limit, args.test)
    existing_output_rows_raw = read_csv_rows(output_path) if args.skip_existing else []
    existing_log_rows = read_csv_rows(log_path) if args.skip_existing else []
    completed_video_ids = {
        row.get("video_id", "")
        for row in existing_output_rows_raw
        if (TXT_DIR / f"{row.get('video_id', '')}.txt").exists()
    }
    existing_output_rows = [row for row in existing_output_rows_raw if row.get("video_id", "") in completed_video_ids]
    rows_to_process = [row for row in input_rows if row.get("video_id", "").strip() not in completed_video_ids]

    api_key = require_gemini_api_key()
    client = genai.Client(api_key=api_key)

    output_rows: list[dict[str, str]] = list(existing_output_rows)
    log_rows: list[dict[str, str]] = list(existing_log_rows)

    audio_success = 0
    audio_fail = 0
    transcribe_success = 0
    transcribe_fail = 0
    clean_success = 0
    txt_success = 0

    def save_progress() -> None:
        nonlocal output_path, log_path
        try:
            write_output(output_path, output_rows)
            write_log(log_path, log_rows)
        except PermissionError:
            pending_output = output_path.with_name(output_path.stem + "_pending.csv")
            pending_log = log_path.with_name(log_path.stem + "_pending.csv")
            write_output(pending_output, output_rows)
            write_log(pending_log, log_rows)
            print(f"CSV path is locked, wrote pending file: {pending_output.resolve()}")
            print(f"Log path is locked, wrote pending file: {pending_log.resolve()}")
            output_path = pending_output
            log_path = pending_log

    for row in rows_to_process:
        video_id = row["video_id"].strip()
        url = row["url"].strip()
        log_row = {
            "processed_at": datetime.now().isoformat(timespec="seconds"),
            "video_id": video_id,
            "url": url,
            "audio_path": "",
            "audio_status": "pending",
            "transcription_status": "pending",
            "cleaning_status": "pending",
            "txt_status": "pending",
            "error": "",
        }

        try:
            audio_path = extract_audio(url, video_id)
            log_row["audio_path"] = str(audio_path)
            log_row["audio_status"] = "success"
            audio_success += 1
        except Exception as exc:
            log_row["audio_status"] = "failed"
            log_row["transcription_status"] = "skipped"
            log_row["cleaning_status"] = "skipped"
            log_row["txt_status"] = "skipped"
            log_row["error"] = f"audio: {exc}"
            audio_fail += 1
            log_rows.append(log_row)
            save_progress()
            continue

        try:
            transcript_raw = transcribe_audio(client, audio_path)
            log_row["transcription_status"] = "success"
            transcribe_success += 1
        except Exception as exc:
            log_row["transcription_status"] = "failed"
            log_row["cleaning_status"] = "skipped"
            log_row["txt_status"] = "skipped"
            log_row["error"] = f"transcription: {exc}"
            transcribe_fail += 1
            log_rows.append(log_row)
            save_progress()
            if "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in str(exc):
                break
            continue

        try:
            transcript_cleaned = clean_transcript(client, transcript_raw)
            log_row["cleaning_status"] = "success"
            clean_success += 1
        except Exception as exc:
            transcript_cleaned = transcript_raw
            log_row["cleaning_status"] = "failed"
            log_row["txt_status"] = "skipped"
            log_row["error"] = f"cleaning: {exc}"
            if "GenerateRequestsPerDayPerProjectPerModel-FreeTier" in str(exc):
                output_rows.append(
                    {
                        "video_id": video_id,
                        "transcript_raw": transcript_raw,
                        "transcript_cleaned": transcript_cleaned,
                        "source_type": "ai_transcription",
                    }
                )
                log_rows.append(log_row)
                save_progress()
                break

        if log_row["cleaning_status"] == "success":
            try:
                save_txt(video_id, transcript_cleaned)
                log_row["txt_status"] = "success"
                txt_success += 1
            except Exception as exc:
                log_row["txt_status"] = "failed"
                log_row["error"] = f"txt: {exc}"

        output_rows.append(
            {
                "video_id": video_id,
                "transcript_raw": transcript_raw,
                "transcript_cleaned": transcript_cleaned,
                "source_type": "ai_transcription",
            }
        )
        log_rows.append(log_row)
        save_progress()

    save_progress()

    print(f"입력 영상 수: {len(input_rows)}")
    print(f"이미 처리되어 건너뛴 수: {len(input_rows) - len(rows_to_process)}")
    print(f"오디오 추출 성공 수: {audio_success}")
    print(f"오디오 추출 실패 수: {audio_fail}")
    print(f"Gemini 전사 성공 수: {transcribe_success}")
    print(f"Gemini 전사 실패 수: {transcribe_fail}")
    print(f"문장 단위 정리 성공 수: {clean_success}")
    print(f"txt 저장 성공 수: {txt_success}")
    print(f"CSV 저장 경로: {output_path.resolve()}")
    print(f"로그 저장 경로: {log_path.resolve()}")


if __name__ == "__main__":
    main()
