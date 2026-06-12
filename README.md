# Trend

한겨레 정치 기사와 유튜브 영상 내용을 수집해 텍스트/CSV 형태로 정리한 데이터 수집 프로젝트입니다.

뉴스 본문은 기사 URL 단위로 저장하고, 유튜브 영상은 오디오를 추출한 뒤 Gemini로 전사 및 문장 정리를 수행합니다.

## 주요 내용

- 한겨레 섹션 페이지에서 기사 링크 수집
- 기사 상세 페이지에서 제목, 날짜, 섹션, 본문, URL 추출
- 기사 본문을 `txt` 파일과 통합 CSV로 저장
- 유튜브 영상 메타데이터 기반 오디오 추출
- Gemini API를 이용한 한국어 전사 및 문장 단위 정리
- 처리 성공/실패 내역을 로그 CSV로 기록

## 파일 구조

```text
trend/
├── README.md
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

## 주요 파일 설명

| 파일 | 역할 |
| --- | --- |
| `crawl_hani_news.py` | 한겨레 섹션 페이지에서 기사 링크를 모으고, 각 기사 본문을 수집해 CSV/TXT로 저장합니다. |
| `update_news_txt_from_article_pages.py` | 기존 `news_raw.csv`의 URL을 다시 방문해 기사 txt 파일을 갱신합니다. |
| `collect_youtube_transcripts.py` | `youtube_meta_raw.csv`의 영상 URL을 기준으로 오디오를 추출하고 Gemini로 전사/정리합니다. |
| `youtube_link.txt` | 수집 대상 유튜브 링크 목록입니다. |
| `requirements.txt` | 실행에 필요한 Python 패키지 목록입니다. |

## 데이터 산출물

| 경로 | 설명 |
| --- | --- |
| `data/processed/news_raw.csv` | 기사 단위 통합 데이터입니다. `article_id`, `title`, `published_date`, `section`, `body_text`, `url` 컬럼을 가집니다. |
| `data/raw/news_txt/정치/*.txt` | 기사 본문을 기사 ID별 텍스트 파일로 저장한 결과입니다. 현재 58개 파일이 포함되어 있습니다. |
| `data/processed/news_crawl_log.csv` | 기사 수집 중 제외/실패/경고가 발생한 내역입니다. |
| `data/processed/youtube_meta_raw.csv` | 유튜브 영상의 기본 메타데이터입니다. |
| `data/processed/youtube_transcript_raw.csv` | 유튜브 영상 전사 원문과 정리본을 함께 저장한 CSV입니다. |
| `data/raw/youtube_transcripts_txt/*.txt` | 유튜브 전사 정리본을 영상 ID별 텍스트 파일로 저장한 결과입니다. 현재 4개 파일이 포함되어 있습니다. |
| `data/processed/youtube_transcript_log.csv` | 유튜브 오디오 추출, 전사, 정리, txt 저장 상태 로그입니다. |

## 작업 방식

### 1. 뉴스 기사 수집

`crawl_hani_news.py`는 한겨레 섹션 페이지를 시작점으로 사용합니다.

목록 페이지에서 `/arti/.../{article_id}.html` 형태의 기사 URL만 추출하고, 중복 URL은 제거합니다. 이후 각 기사 상세 페이지를 방문해 제목, 발행일, 섹션, 본문을 파싱합니다.

본문은 우선 `requests`와 `BeautifulSoup`로 추출하고, 본문이 충분히 수집되지 않는 경우 Playwright로 페이지를 렌더링해 다시 시도합니다. 광고, 이미지 캡션, 관련 기사, 기자 정보처럼 분석에 방해되는 요소는 제거한 뒤 저장합니다.

### 2. 기사 txt 갱신

`update_news_txt_from_article_pages.py`는 이미 만들어진 `news_raw.csv`를 기준으로 기사 URL을 다시 방문합니다.

CSV에 기록된 `article_id`와 `url`을 읽고, 최신 파싱 로직으로 본문 txt 파일을 덮어쓰거나 새로 생성합니다. 이 과정에서 실패한 항목은 별도 로그에 남기도록 구성되어 있습니다.

### 3. 유튜브 전사 수집

`collect_youtube_transcripts.py`는 `youtube_meta_raw.csv`의 `video_id`, `url`을 입력으로 사용합니다.

`yt-dlp`로 영상 오디오를 추출하고, `imageio-ffmpeg`가 제공하는 ffmpeg 실행 파일로 mp3 변환을 처리합니다. 변환된 오디오는 Gemini Files API에 업로드한 뒤 전사하고, 다시 Gemini로 문장 단위 정리를 수행합니다.

전사 결과는 CSV에 원문과 정리본을 함께 남기고, 읽기 쉬운 정리본은 `data/raw/youtube_transcripts_txt/{video_id}.txt`로 저장합니다. API 키는 `.env`의 `GEMINI_API_KEY`를 사용하며, `.env`와 오디오 원본 파일은 Git에 포함하지 않습니다.

## 실행 방법

필요 패키지를 설치합니다.

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

한겨레 정치 섹션을 테스트 수집합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti/politics" --test
```

여러 페이지를 수집합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti/politics" --max-pages 5 --delay 1
```

기존 기사 URL 기준으로 txt 파일을 갱신합니다.

```bash
python update_news_txt_from_article_pages.py --input data/processed/news_raw.csv
```

유튜브 전사를 테스트 실행합니다.

```bash
python collect_youtube_transcripts.py --test
```

이미 처리된 영상은 건너뛰고 이어서 실행합니다.

```bash
python collect_youtube_transcripts.py --skip-existing
```

## 환경 변수

유튜브 전사 기능을 사용하려면 프로젝트 루트에 `.env` 파일을 만들고 Gemini API 키를 설정합니다.

```text
GEMINI_API_KEY=your_api_key_here
```

선택적으로 사용할 모델명을 바꿀 수 있습니다.

```text
GEMINI_MODEL=gemini-2.5-flash
```

## Git 관리 기준

다음 항목은 저장소에 포함하지 않습니다.

- `.env`: API 키 등 민감 정보
- `__pycache__/`: Python 캐시
- `data/raw/youtube_audio/`: 유튜브에서 추출한 대용량 오디오 원본

CSV, 기사 txt, 유튜브 전사 txt는 결과 확인과 재사용을 위해 저장소에 포함했습니다.
