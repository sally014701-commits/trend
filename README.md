# Trend 뉴스·유튜브 텍스트 분석 프로젝트

한겨레 기사와 유튜브 영상 내용을 수집하고, 분석 가능한 정제 텍스트·세그먼트·형태소 토큰·TF-IDF·불용어 후보 파일로 정리한 프로젝트입니다.

현재 데이터 흐름은 크게 세 단계입니다.

1. `data/processed`: 원천 수집 결과
2. `data/02_processing`: 분석 전 정제·세그먼트화 결과
3. `data/03_processing`: Kiwi 형태소 분석, TF-IDF, 불용어 후보 결과

`.env`, Python/Node 캐시, 대용량 유튜브 오디오 원본은 저장소에서 제외합니다.

## 전체 구성

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
    ├── 02_processing/
    │   ├── news_clean.csv
    │   ├── news_clean.xlsx
    │   ├── youtube_clean.csv
    │   ├── youtube_clean.xlsx
    │   ├── youtube_segments.csv
    │   ├── youtube_segments.xlsx
    │   ├── metadata_clean.csv
    │   └── youtube_clean_txt/
    ├── 03_processing/
    │   ├── tokens_news.csv
    │   ├── tokens_youtube.csv
    │   ├── kiwi_user_words_youtube.csv
    │   └── stopwords.xlsx
    └── raw/
        ├── news_txt/
        ├── youtube_transcripts_txt/
        └── youtube_audio/   # 로컬 전용, Git 제외
```

## 루트 파일

| 파일 | 설명 |
| --- | --- |
| `crawl_hani_news.py` | 한겨레 기사 목록과 상세 페이지를 수집해 `news_raw.csv`와 기사별 txt를 생성합니다. |
| `update_news_txt_from_article_pages.py` | 기존 `news_raw.csv`의 URL을 다시 방문해 기사 txt를 재생성하는 보조 스크립트입니다. |
| `collect_youtube_transcripts.py` | 유튜브 오디오를 추출하고 Gemini API로 전사·정리해 CSV/txt로 저장합니다. |
| `youtube_link.txt` | 수집 대상 유튜브 URL 목록입니다. |
| `requirements.txt` | 수집/전사 스크립트 실행에 필요한 Python 패키지 목록입니다. |
| `.gitignore` | `.env`, 캐시, 대용량 오디오, `node_modules`, `.codex_tmp` 등을 제외합니다. |

## 데이터 산출물

### 1. 원천 수집 데이터: `data/processed`

| 경로 | 행 수 | 주요 컬럼 | 설명 |
| --- | ---: | --- | --- |
| `data/processed/news_raw.csv` | 292 | `article_id`, `title`, `published_date`, `section`, `body_text`, `url` | 한겨레 기사 원문 수집 결과입니다. |
| `data/processed/news_crawl_log.csv` | - | `article_id`, `url`, `status`, `reason`, `section`, `sub_section`, `occurred_at` | 뉴스 수집 중 제외·실패·경고 내역입니다. |
| `data/processed/youtube_meta_raw.csv` | - | `video_id`, `channel`, `title`, `upload_date`, `description`, `view_count`, `duration`, `url` | 유튜브 영상 메타데이터입니다. |
| `data/processed/youtube_transcript_raw.csv` | - | `video_id`, `transcript_raw`, `transcript_cleaned`, `source_type` | Gemini 전사 원문과 정리본입니다. |
| `data/processed/youtube_transcript_log.csv` | - | `processed_at`, `video_id`, `url`, `audio_path`, `audio_status`, `transcription_status`, `cleaning_status`, `txt_status`, `error` | 유튜브 처리 로그입니다. |

### 2. 정제 데이터: `data/02_processing`

| 경로 | 행 수 | 주요 컬럼 | 설명 |
| --- | ---: | --- | --- |
| `data/02_processing/news_clean.csv` | 292 | `article_id`, `title`, `published_date`, `section`, `body_text`, `url` | 분석용으로 정제한 뉴스 본문입니다. 한겨레 뉴스레터 안내문 등 노이즈를 제거했고, 본문이 `(`로 깨졌던 8개 행은 원본에서 복구했습니다. |
| `data/02_processing/news_clean.xlsx` | 292 | 동일 | Excel 검토용 뉴스 정제본입니다. |
| `data/02_processing/youtube_clean.csv` | - | `video_id`, `transcript_raw`, `transcript_cleaned`, `source_type` | 유튜브 전사 정리본입니다. |
| `data/02_processing/youtube_clean.xlsx` | - | 동일 | Excel 검토용 유튜브 정리본입니다. |
| `data/02_processing/youtube_segments.csv` | 93 | `segment_id`, `video_id`, `seg_idx`, `seg_type`, `book_title`, `segment_text`, `verified` | 유튜브 전사문을 세그먼트 단위로 나눈 파일입니다. |
| `data/02_processing/youtube_segments.xlsx` | 93 | `segment_id`, `video_id`, `seg_idx`, `seg_type`, `book_title`, `author`, `segment_text`, `verified`, `channel`, `upload_date` | 토큰화에 사용한 Excel 세그먼트 파일입니다. |
| `data/02_processing/metadata_clean.csv` | - | - | 유튜브/도서 메타데이터 정제본입니다. |
| `data/02_processing/youtube_clean_txt/*.txt` | 12 | - | 정제된 유튜브 전사 txt입니다. |

### 3. 토큰·TF-IDF·불용어 데이터: `data/03_processing`

| 경로 | 행 수 | 주요 컬럼 | 설명 |
| --- | ---: | --- | --- |
| `data/03_processing/tokens_news.csv` | 49,562 | `article_id`, `published_date`, `section`, `token`, `pos`, `count`, `tfidf` | 뉴스 본문을 Kiwi로 형태소 분석한 토큰 테이블입니다. 문서 단위는 `article_id`입니다. |
| `data/03_processing/tokens_youtube.csv` | 7,363 | `segment_id`, `video_id`, `channel`, `upload_date`, `book_title`, `author`, `token`, `pos`, `count`, `tfidf` | 유튜브 `seg_type == book` 세그먼트를 Kiwi로 분석한 토큰 테이블입니다. 문서 단위는 `segment_id`입니다. |
| `data/03_processing/kiwi_user_words_youtube.csv` | 122 | `word`, `pos` | 유튜브 토큰화 전 `book_title`, `author` 고유값에서 추출해 Kiwi 사용자 사전에 등록한 단어 목록입니다. |
| `data/03_processing/stopwords.xlsx` | - | 시트별 상이 | 뉴스/유튜브 불용어 후보와 최종 불용어 시트입니다. |

`stopwords.xlsx` 시트 구성은 다음과 같습니다.

| 시트 | 설명 |
| --- | --- |
| `news_candidates` | 뉴스 불용어 후보입니다. 기준은 `tfidf <= 2`인 문서-토큰 행이 하나라도 있거나 `doc_freq_ratio >= 0.5`인 토큰입니다. |
| `yt_candidates` | 유튜브 불용어 후보입니다. 같은 기준을 적용했습니다. |
| `news_stopwords` | 뉴스 최종 불용어 13개입니다. |
| `yt_stopwords` | 유튜브 최종 불용어 22개입니다. 유튜브 후보 중 `책`, `읽다`, `소설`, `작가`, `마음`, `느끼다`, `쓰다`, `좋아하다`, `좋다`, `재밌다`는 최종 불용어에서 제외했습니다. |

## 형태소 분석 기준

Kiwi 형태소 분석은 다음 기준으로 수행했습니다.

- 뉴스 분석 단위: 기사 1행, 즉 `article_id`
- 유튜브 분석 단위: `seg_type == book`인 세그먼트 1행, 즉 `segment_id`
- 추출 품사: `NNG`, `NNP`, `VA`, `VV`
- 동사/형용사 원형 복원: `읽었습니다` → `읽다`, `힘들었어요` → `힘들다`
- `count`: 각 문서 안에서 동일 `token + pos`가 등장한 횟수
- 인코딩: `utf-8-sig`

유튜브 토큰화 전에는 `youtube_segments.xlsx`의 `book_title`, `author` 고유값을 Kiwi 사용자 사전에 `NNP`로 등록했습니다. `author` 값에 `한강;정보라`처럼 세미콜론이 있으면 각각 나누어 등록했습니다.

## TF-IDF 계산 기준

`tokens_news.csv`, `tokens_youtube.csv`의 `tfidf` 컬럼은 문서별 개별 점수입니다. 평균값이 아닙니다.

```text
TF  = count(token, doc)
IDF = log((1 + N) / (1 + df(token))) + 1
TF-IDF = TF * IDF
```

- 뉴스의 `N`: 전체 기사 수 292
- 유튜브의 `N`: `seg_type == book` 세그먼트 수 65
- `df(token)`: 해당 토큰이 등장한 문서 수

## 불용어 후보 계산 기준

불용어 후보 집계 테이블은 다음 컬럼으로 구성됩니다.

```text
token | pos | total_count | doc_freq | doc_freq_ratio | tfidf_avg
```

- `total_count`: 전체 문서에서 해당 토큰의 count 합산
- `doc_freq`: 해당 토큰이 등장한 문서 수
- `doc_freq_ratio`: `doc_freq / 전체 문서 수`
- `tfidf_avg`: 해당 토큰의 문서별 TF-IDF 평균
- `pos`: 같은 토큰이 여러 품사로 나뉘면 최빈 품사

현재 `stopwords.xlsx` 후보 시트에는 다음 OR 조건을 적용했습니다.

```text
tfidf <= 2 인 문서-토큰 행이 하나라도 있음
OR
doc_freq_ratio >= 0.5
```

## 스크립트별 작업 방식

### `crawl_hani_news.py`

한겨레 섹션 페이지를 입력으로 받아 기사 URL을 수집하고, 각 기사 상세 페이지에서 본문 데이터를 추출합니다.

주요 흐름:

1. 입력 섹션 URL 접속
2. `/arti/.../{article_id}.html` 기사 링크 필터링
3. 중복 URL 제거
4. 기사 제목, 발행일, 섹션, 본문 추출
5. 광고, 이미지 캡션, 관련 기사, 기자 정보 제거
6. 본문이 짧거나 비어 있으면 Playwright 렌더링 후 재시도
7. 기사별 txt를 `data/raw/news_txt/{section}/{article_id}.txt`에 저장
8. 통합 CSV를 `data/processed/news_raw.csv`에 저장
9. 실패·제외·경고를 `data/processed/news_crawl_log.csv`에 기록

### `update_news_txt_from_article_pages.py`

`data/processed/news_raw.csv`의 `article_id`, `url`을 기준으로 기사 상세 페이지를 다시 방문해 txt 본문을 재생성합니다. 본문 추출 로직 수정 후 txt만 갱신할 때 사용하는 보조 스크립트입니다.

### `collect_youtube_transcripts.py`

유튜브 영상 오디오를 추출하고 Gemini API로 한국어 전사문을 생성·정리합니다.

주요 흐름:

1. `youtube_meta_raw.csv`에서 영상 ID와 URL 읽기
2. `yt-dlp`로 오디오 다운로드
3. `imageio-ffmpeg` 기반 ffmpeg로 mp3 생성
4. Gemini Files API 업로드
5. Gemini 모델로 한국어 전사 생성
6. 전사문을 문장 단위로 정리
7. CSV와 txt 저장
8. 처리 로그 기록

## 실행 방법

패키지를 설치합니다.

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

한겨레 섹션을 테스트 수집합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti/politics" --test
```

한겨레 섹션 여러 페이지를 수집합니다.

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
| 뉴스 원천 기사 | `news_raw.csv` 292행 |
| 뉴스 정제본 | `news_clean.csv`, `news_clean.xlsx` 292행 |
| 유튜브 세그먼트 | `youtube_segments.csv`, `youtube_segments.xlsx` 93행 |
| 뉴스 토큰 | `tokens_news.csv` 49,562행, 문서 수 292 |
| 유튜브 토큰 | `tokens_youtube.csv` 7,363행, book 세그먼트 문서 수 65 |
| Kiwi 사용자 사전 | `kiwi_user_words_youtube.csv` 122개 |
| 최종 불용어 | `stopwords.xlsx` 안의 `news_stopwords` 13개, `yt_stopwords` 22개 |

## GitHub 포함/제외 기준

GitHub에 포함하는 항목은 코드, README, 수집 대상 링크, CSV/XLSX 산출물, txt 산출물입니다.

GitHub에서 제외하는 항목은 다음과 같습니다.

- `.env`: Gemini API 키 등 민감 정보 포함
- `__pycache__/`: Python 실행 캐시
- `data/raw/youtube_audio/`: 유튜브 mp3/webm 원본으로 파일 크기가 큼
- `.venv/`, `venv/`, `env/`: 로컬 가상환경
- `.pytest_cache/`, `.mypy_cache/`: 개발 도구 캐시
- `node_modules/`: 로컬 Node 의존성
- `.codex_tmp/`: 작업용 임시 파일
