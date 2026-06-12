# Trend 뉴스·유튜브 텍스트 수집 프로젝트

한겨레 정치 기사와 유튜브 영상 내용을 수집해 분석 가능한 텍스트/CSV 형태로 정리한 프로젝트입니다. 뉴스는 기사 본문을 수집하고, 유튜브는 영상 오디오를 추출한 뒤 Gemini API로 전사 및 문장 정리를 수행했습니다.

이 저장소는 코드만이 아니라 실제 수집 결과 CSV와 txt 산출물도 함께 포함합니다. 단, API 키가 들어가는 `.env`와 대용량 유튜브 오디오 원본은 GitHub에 올리지 않았습니다.

## 전체 구성 요약

```text
trend/
├── README.md
├── .gitignore
├── requirements.txt
├── youtube_link.txt
├── crawl_hani_news.py
├── update_news_txt_from_article_pages.py
├── collect_youtube_transcripts.py
└── data/
    ├── processed/
    │   ├── news_raw.csv
    │   ├── news_crawl_log.csv
    │   ├── youtube_meta_raw.csv
    │   ├── youtube_transcript_raw.csv
    │   └── youtube_transcript_log.csv
    └── raw/
        ├── news_txt/
        │   └── 정치/
        │       └── {article_id}.txt
        └── youtube_transcripts_txt/
            └── {video_id}.txt
```

로컬 작업 폴더에는 `data/raw/youtube_audio/`도 존재합니다. 이 폴더에는 유튜브 영상에서 추출한 mp3 오디오 11개가 들어 있지만, 파일 크기가 커서 `.gitignore`로 제외했습니다.

## 루트 파일 설명

| 파일 | 포함 내용 | 확인 포인트 |
| --- | --- | --- |
| `README.md` | 프로젝트 목적, 파일 구조, 작업 방식, 실행 방법을 정리한 안내 문서입니다. | GitHub 저장소 첫 화면에서 바로 보이는 문서입니다. |
| `.gitignore` | GitHub에 올리지 않을 파일 목록입니다. | `.env`, Python 캐시, 유튜브 오디오 mp3 원본을 제외합니다. |
| `requirements.txt` | 프로젝트 실행에 필요한 Python 패키지 목록입니다. | `requests`, `beautifulsoup4`, `lxml`, `playwright`, `yt-dlp`, `google-genai`, `imageio-ffmpeg`가 포함됩니다. |
| `youtube_link.txt` | 유튜브 수집 대상 링크 목록입니다. | 총 11개의 유튜브 URL이 들어 있습니다. |
| `crawl_hani_news.py` | 한겨레 기사 목록/상세 페이지를 수집하는 메인 크롤러입니다. | 기사 URL 수집, 본문 파싱, txt 저장, CSV 저장, 로그 기록을 수행합니다. |
| `update_news_txt_from_article_pages.py` | 이미 수집된 기사 URL을 다시 방문해 txt 본문 파일을 갱신하는 보조 스크립트입니다. | `news_raw.csv`의 `article_id`, `url`을 기준으로 txt를 재생성합니다. |
| `collect_youtube_transcripts.py` | 유튜브 오디오를 추출하고 Gemini로 전사/정리하는 메인 스크립트입니다. | mp3 추출, Gemini 업로드, 전사, 문장 정리, CSV/txt 저장을 수행합니다. |

## 데이터 파일 설명

### 뉴스 데이터

| 경로 | 포함 내용 |
| --- | --- |
| `data/processed/news_raw.csv` | 기사 단위 통합 CSV입니다. `article_id`, `title`, `published_date`, `section`, `body_text`, `url` 컬럼을 포함합니다. |
| `data/processed/news_crawl_log.csv` | 기사 수집 중 발생한 제외, 실패, 경고 내역입니다. `article_id`, `url`, `status`, `reason`, `section`, `sub_section`, `occurred_at` 컬럼을 포함합니다. |
| `data/raw/news_txt/정치/*.txt` | 기사 본문을 기사 ID별 txt 파일로 저장한 결과입니다. 현재 58개 파일이 포함되어 있습니다. |

### 유튜브 데이터

| 경로 | 포함 내용 |
| --- | --- |
| `data/processed/youtube_meta_raw.csv` | 유튜브 영상 메타데이터 CSV입니다. `video_id`, `channel`, `title`, `upload_date`, `description`, `view_count`, `duration`, `url` 컬럼을 포함합니다. |
| `data/processed/youtube_transcript_raw.csv` | Gemini 전사 결과 CSV입니다. `video_id`, `transcript_raw`, `transcript_cleaned`, `source_type` 컬럼을 포함합니다. |
| `data/processed/youtube_transcript_log.csv` | 유튜브 처리 로그입니다. `processed_at`, `video_id`, `url`, `audio_path`, `audio_status`, `transcription_status`, `cleaning_status`, `txt_status`, `error` 컬럼을 포함합니다. |
| `data/raw/youtube_transcripts_txt/*.txt` | 전사 정리본을 영상 ID별 txt 파일로 저장한 결과입니다. 현재 4개 파일이 포함되어 있습니다. |
| `data/raw/youtube_audio/*.mp3` | 유튜브 영상에서 추출한 오디오 원본입니다. 로컬에는 11개가 있으나 GitHub에는 포함하지 않았습니다. |

## 스크립트별 작업 방식

### 1. `crawl_hani_news.py`

한겨레 섹션 페이지를 입력으로 받아 기사 URL을 수집하고, 각 기사 상세 페이지에서 본문 데이터를 추출합니다.

주요 처리 흐름은 다음과 같습니다.

1. 입력받은 섹션 URL에 접속합니다.
2. `/arti/.../{article_id}.html` 형태의 기사 링크만 필터링합니다.
3. 중복 URL을 제거합니다.
4. 각 기사 상세 페이지에서 제목, 발행일, 섹션, 하위 섹션, 본문을 추출합니다.
5. 광고, 이미지 캡션, 관련 기사, 기자 정보 등 분석에 불필요한 요소를 제거합니다.
6. 본문이 짧거나 비어 있으면 Playwright로 렌더링한 뒤 다시 추출합니다.
7. 기사 본문은 `data/raw/news_txt/정치/{article_id}.txt`로 저장합니다.
8. 전체 기사 데이터는 `data/processed/news_raw.csv`로 저장합니다.
9. 실패하거나 제외된 항목은 `data/processed/news_crawl_log.csv`에 기록합니다.

사용한 주요 라이브러리는 `requests`, `BeautifulSoup`, `lxml`, `playwright`입니다.

### 2. `update_news_txt_from_article_pages.py`

이미 만들어진 `data/processed/news_raw.csv`를 기준으로 기사 txt 파일을 다시 생성하는 스크립트입니다.

이 스크립트는 CSV 안의 `article_id`와 `url`을 읽고, 각 URL을 다시 방문해 본문을 추출합니다. 기존 txt 파일이 있으면 덮어쓰고, 없으면 새로 만듭니다. 기사 본문 추출 로직을 수정했거나 txt 파일만 다시 정리하고 싶을 때 사용하는 보조 작업용 파일입니다.

처리 실패 내역은 `data/processed/news_txt_update_log.csv`에 저장되도록 코드가 구성되어 있습니다. 현재 GitHub에 올라간 산출물에는 해당 로그 파일이 생성되어 있지 않습니다.

### 3. `collect_youtube_transcripts.py`

유튜브 영상 내용을 텍스트로 바꾸는 스크립트입니다. `youtube_meta_raw.csv`의 `video_id`와 `url`을 기준으로 작업합니다.

주요 처리 흐름은 다음과 같습니다.

1. `data/processed/youtube_meta_raw.csv`에서 영상 ID와 URL을 읽습니다.
2. `yt-dlp`로 유튜브 영상의 오디오를 다운로드합니다.
3. `imageio-ffmpeg`가 제공하는 ffmpeg로 mp3를 생성합니다.
4. mp3 파일을 Gemini Files API에 업로드합니다.
5. Gemini 모델로 한국어 전사문을 생성합니다.
6. 전사문을 다시 Gemini에 보내 문장 단위로 정리합니다.
7. 원문 전사와 정리본을 `data/processed/youtube_transcript_raw.csv`에 저장합니다.
8. 정리본은 `data/raw/youtube_transcripts_txt/{video_id}.txt`로 따로 저장합니다.
9. 오디오 추출, 전사, 정리, txt 저장 상태를 `data/processed/youtube_transcript_log.csv`에 남깁니다.

Gemini API 키는 `.env` 파일의 `GEMINI_API_KEY`를 사용합니다. `.env`는 민감 정보이므로 저장소에 포함하지 않았습니다.

## 실행 방법

패키지를 설치합니다.

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

한겨레 정치 섹션을 테스트 수집합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti/politics" --test
```

한겨레 정치 섹션 여러 페이지를 수집합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti/politics" --max-pages 5 --delay 1
```

기존 기사 URL을 기준으로 txt 파일을 다시 생성합니다.

```bash
python update_news_txt_from_article_pages.py --input data/processed/news_raw.csv
```

유튜브 전사를 1개 영상만 테스트합니다.

```bash
python collect_youtube_transcripts.py --test
```

이미 처리된 영상은 건너뛰고 이어서 전사합니다.

```bash
python collect_youtube_transcripts.py --skip-existing
```

## 환경 변수

유튜브 전사 기능을 실행하려면 프로젝트 루트에 `.env` 파일이 필요합니다.

```text
GEMINI_API_KEY=your_api_key_here
```

필요하면 사용할 Gemini 모델명을 바꿀 수 있습니다.

```text
GEMINI_MODEL=gemini-2.5-flash
```

## 현재 산출물 현황

| 구분 | 현재 상태 |
| --- | --- |
| 유튜브 링크 목록 | `youtube_link.txt`에 11개 URL |
| 유튜브 오디오 원본 | 로컬 `data/raw/youtube_audio/`에 11개 mp3, GitHub 제외 |
| 유튜브 전사 txt | `data/raw/youtube_transcripts_txt/`에 4개 |
| 유튜브 전사 CSV | `data/processed/youtube_transcript_raw.csv`에 저장 |
| 뉴스 기사 txt | `data/raw/news_txt/정치/`에 58개 |
| 뉴스 기사 CSV | `data/processed/news_raw.csv`에 저장 |

## GitHub 포함/제외 기준

GitHub에 포함한 항목은 코드, README, 수집 대상 링크, CSV 산출물, txt 산출물입니다.

GitHub에서 제외한 항목은 다음과 같습니다.

- `.env`: Gemini API 키 등 민감 정보 포함
- `__pycache__/`: Python 실행 캐시
- `data/raw/youtube_audio/`: 유튜브 mp3 원본으로 파일 크기가 큼
- `.venv/`, `venv/`, `env/`: 로컬 가상환경
- `.pytest_cache/`, `.mypy_cache/`: 개발 도구 캐시
