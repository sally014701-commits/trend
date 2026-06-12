# 한겨레 1페이지 뉴스 수집기

입력한 한겨레 섹션 1페이지 URL에서 기사 링크를 모으고, 각 기사 본문을 저장해 `news_raw.csv`를 만듭니다. 최근 3개월 전체 수집이나 페이지네이션은 구현하지 않은 최소 작동 버전입니다.

## 설치

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Playwright는 목록 또는 상세 페이지가 정적 HTML만으로 파싱되지 않을 때 fallback 용도로 사용합니다.

## 실행

먼저 기사 5개만 테스트합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti?page=1" --test
```

1페이지의 모든 기사 링크를 대상으로 실행합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti?page=1"
```

요청 간격을 늘리고 싶으면 `--delay`를 사용합니다.

```bash
python crawl_hani_news.py "https://www.hani.co.kr/arti?page=1" --delay 2
```

## 출력 파일

- 본문 txt: `data/raw/news_txt/{article_id}.txt`
- 통합 CSV: `data/processed/news_raw.csv`
- 실패/경고 로그: `data/processed/news_crawl_log.csv`

`news_raw.csv`는 엑셀에서 한글이 깨지지 않도록 `utf-8-sig`로 저장합니다.

## CSV 컬럼

```text
article_id,title,published_date,section,body_text,url
```

## 수집 방식

- 목록 페이지에서 `/arti/.../{article_id}.html` 형태의 기사 URL만 수집합니다.
- 중복 URL은 제거합니다.
- 기사 상세 페이지는 `requests`와 `BeautifulSoup`으로 먼저 파싱합니다.
- 본문이 비어 있거나 너무 짧으면 Playwright로 한 번 더 시도합니다.
- 그래도 본문이 짧으면 해당 기사는 제외하고 로그에 남깁니다.
- `section`은 상세 페이지 breadcrumb의 첫 번째 `/arti/` 링크 텍스트를 우선 사용합니다.
- breadcrumb를 찾지 못하면 목록에서 추정한 섹션명을 사용하고, 없으면 `unknown`으로 저장합니다.
- 날짜는 가능한 경우 `YYYY-MM-DD` 형식으로 정리합니다.

## 실행 후 콘솔 검증 항목

실행이 끝나면 다음 항목을 출력합니다.

- 수집한 기사 URL 수
- 중복 제거 후 기사 수
- 본문 파싱 성공 기사 수
- 본문 파싱 실패 기사 수
- 섹션별 기사 수
- 날짜 범위
- `news_raw.csv` 저장 경로
- txt 파일 저장 개수
