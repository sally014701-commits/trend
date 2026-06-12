import argparse
import csv
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


USER_AGENT = "Mozilla/5.0 (compatible; TrendCrawler/1.0; +https://www.hani.co.kr/)"
DEFAULT_INPUT_CSV = Path("data") / "processed" / "news_raw.csv"
DEFAULT_TXT_DIR = Path("data") / "raw" / "news_txt"
LOG_CSV = Path("data") / "processed" / "news_txt_update_log.csv"
REQUEST_DELAY_SECONDS = 1.0
MIN_BODY_LENGTH = 100


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.5",
        }
    )
    return session


def can_fetch(url: str) -> bool:
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        response = requests.get(robots_url, headers={"User-Agent": USER_AGENT}, timeout=10)
        response.raise_for_status()

        in_generic_block = False
        disallow_rules = []
        for raw_line in response.text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()

            if key == "user-agent":
                if in_generic_block and value != "*":
                    break
                in_generic_block = value == "*"
                continue
            if in_generic_block and key == "disallow" and value:
                disallow_rules.append(value)

        return not any(parsed.path.startswith(rule) for rule in disallow_rules)
    except Exception:
        return True


def fetch_article_html(url: str, session: requests.Session) -> str:
    if not can_fetch(url):
        raise RuntimeError(f"robots.txt disallows fetching: {url}")
    response = session.get(url, timeout=20)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def extract_next_article(soup: BeautifulSoup) -> Dict:
    script = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if not script or not script.string:
        return {}
    try:
        data = json.loads(script.string)
        return data.get("props", {}).get("pageProps", {}).get("article", {}) or {}
    except Exception:
        return {}


def strip_noise_nodes(node: BeautifulSoup) -> None:
    selectors = (
        "figure, figcaption, picture, img, script, style, noscript, iframe, audio, "
        "[class*='Ad'], [class*='ad'], [class*='Caption'], [class*='caption'], "
        "[class*='Related'], [class*='related'], [class*='Audio'], [class*='audio'], "
        "[class*='reporter'], [class*='Reporter'], [class*='copyright'], [class*='Copyright']"
    )
    for removable in node.select(selectors):
        removable.decompose()


def clean_paragraph_text(text: str) -> str:
    text = re.sub(r"\[%%[^%]+%%\]", " ", text or "")
    text = re.sub(r"\s+", " ", text)
    text = text.strip()

    noise_patterns = [
        r"^광고$",
        r"^구독$",
        r"^관련기사.*",
        r"^기사 읽어드립니다.*",
        r"^한겨레.*구독.*",
        r"^©.*",
        r"^무단 전재.*",
        r"^AI 학습 및 활용 금지.*",
        r"^.*?기자\s+[A-Za-z0-9._%+-]+@hani\.co\.kr$",
    ]
    if any(re.search(pattern, text) for pattern in noise_patterns):
        return ""
    return text


def split_korean_sentences(paragraph: str) -> List[str]:
    paragraph = re.sub(r"\s+", " ", paragraph).strip()
    if not paragraph:
        return []

    protected = paragraph
    placeholders = {}
    abbreviation_patterns = [
        r"\d+\.\d+",
        r"[A-Za-z]\.",
        r"[가-힣]{1,4}\([^)]+\)",
    ]
    for pattern in abbreviation_patterns:
        for match in re.finditer(pattern, protected):
            key = f"__P{len(placeholders)}__"
            placeholders[key] = match.group(0)
            protected = protected.replace(match.group(0), key, 1)

    split_pattern = re.compile(r"(?<=[.!?])\s+")
    parts = [part.strip() for part in split_pattern.split(protected) if part.strip()]

    restored = []
    for part in parts:
        for key, value in placeholders.items():
            part = part.replace(key, value)
        restored.append(part)
    return restored


def format_txt(paragraphs: List[str]) -> str:
    formatted_paragraphs = []
    for paragraph in paragraphs:
        sentences = split_korean_sentences(paragraph)
        if sentences:
            formatted_paragraphs.append("\n".join(sentences))
    return "\n\n".join(formatted_paragraphs).strip() + "\n"


def extract_paragraphs_from_html_fragment(html_fragment: str) -> List[str]:
    soup = make_soup(html_fragment)
    strip_noise_nodes(soup)
    paragraphs = []
    p_tags = soup.select("p")
    if p_tags:
        for p_tag in p_tags:
            text = clean_paragraph_text(p_tag.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
    else:
        text = clean_paragraph_text(soup.get_text(" ", strip=True))
        if text:
            paragraphs.append(text)
    return paragraphs


def extract_article_paragraphs(soup: BeautifulSoup) -> List[str]:
    next_article = extract_next_article(soup)
    content_html = next_article.get("content")
    if content_html:
        paragraphs = extract_paragraphs_from_html_fragment(content_html)
        if paragraphs:
            return paragraphs

    candidate_selectors = [
        ".article-text",
        "article .article-text",
        "article",
        "#content article",
        "#content",
        "div[class*='ArticleDetailContent']",
        "div[class*='ArticleDetail_viewWrap']",
    ]

    for selector in candidate_selectors:
        node = soup.select_one(selector)
        if not node:
            continue

        node_copy = make_soup(str(node))
        strip_noise_nodes(node_copy)
        paragraphs = []
        for p_tag in node_copy.select("p"):
            text = clean_paragraph_text(p_tag.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
        if len(" ".join(paragraphs)) >= MIN_BODY_LENGTH:
            return paragraphs

    return []


def read_input_rows(input_csv: Path) -> List[Dict[str, str]]:
    with input_csv.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            article_id = (row.get("article_id") or "").strip()
            url = (row.get("url") or "").strip()
            if article_id and url:
                rows.append({"article_id": article_id, "url": url})
        return rows


def save_update_log(log_rows: List[Dict[str, str]]) -> Path:
    LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    columns = ["article_id", "url", "reason", "occurred_at"]
    with LOG_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in log_rows:
            writer.writerow(row)
    return LOG_CSV


def update_txt_files(rows: List[Dict[str, str]], txt_dir: Path, delay: float) -> Dict[str, int]:
    txt_dir.mkdir(parents=True, exist_ok=True)
    session = build_session()
    log_rows: List[Dict[str, str]] = []
    stats = {
        "success": 0,
        "failed": 0,
        "overwritten": 0,
        "created": 0,
    }

    for row in rows:
        article_id = row["article_id"]
        url = row["url"]
        try:
            time.sleep(max(delay, 0))
            html = fetch_article_html(url, session)
            soup = make_soup(html)
            paragraphs = extract_article_paragraphs(soup)
            body_length = len(" ".join(paragraphs))
            if body_length < MIN_BODY_LENGTH:
                raise ValueError(f"본문이 비어 있거나 너무 짧음: {body_length}자")

            txt_path = txt_dir / f"{article_id}.txt"
            existed = txt_path.exists()
            txt_path.write_text(format_txt(paragraphs), encoding="utf-8")

            stats["success"] += 1
            if existed:
                stats["overwritten"] += 1
            else:
                stats["created"] += 1
        except Exception as exc:
            stats["failed"] += 1
            log_rows.append(
                {
                    "article_id": article_id,
                    "url": url,
                    "reason": str(exc),
                    "occurred_at": datetime.now().isoformat(timespec="seconds"),
                }
            )
            continue

    save_update_log(log_rows)
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 news_raw.csv URL로 기사 상세 본문 txt를 다시 저장합니다.")
    parser.add_argument("--test", action="store_true", help="앞의 5개 기사만 처리")
    parser.add_argument("--limit", type=int, default=None, help="앞의 N개 기사만 처리")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_CSV, help="입력 CSV 경로")
    parser.add_argument("--txt-dir", type=Path, default=DEFAULT_TXT_DIR, help="txt 저장 폴더")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS, help="요청 간 딜레이(초)")
    args = parser.parse_args()

    rows = read_input_rows(args.input)
    total_rows = len(rows)
    if args.test:
        rows = rows[:5]
    elif args.limit is not None:
        rows = rows[: max(args.limit, 0)]

    stats = update_txt_files(rows, args.txt_dir, args.delay)

    print(f"전체 기사 수: {total_rows}")
    print(f"txt 업데이트 성공 수: {stats['success']}")
    print(f"txt 업데이트 실패 수: {stats['failed']}")
    print(f"기존 txt 덮어쓰기 수: {stats['overwritten']}")
    print(f"새 txt 생성 수: {stats['created']}")
    print(f"로그 저장 경로: {LOG_CSV}")


if __name__ == "__main__":
    main()
