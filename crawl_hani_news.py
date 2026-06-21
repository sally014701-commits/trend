import argparse
import csv
import hashlib
import json
import re
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.hani.co.kr"
USER_AGENT = "Mozilla/5.0 (compatible; TrendCrawler/1.0; +https://www.hani.co.kr/)"
REQUEST_DELAY_SECONDS = 1.0
MIN_BODY_LENGTH = 100

RAW_TXT_DIR = Path("data") / "raw" / "news_txt"
PROCESSED_DIR = Path("data") / "processed"
NEWS_RAW_CSV = PROCESSED_DIR / "news_raw.csv"
NEWS_LOG_CSV = PROCESSED_DIR / "news_crawl_log.csv"
SECTION_NAME_BY_SLUG = {
    "politics": "정치",
    "society": "사회",
    "economy": "경제",
    "culture": "문화",
    "science": "기술과학",
}

LOG_ROWS: List[Dict[str, str]] = []


def ensure_dirs() -> None:
    RAW_TXT_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html, "lxml")
    except Exception:
        return BeautifulSoup(html, "html.parser")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def add_log(
    url: str,
    reason: str,
    status: str = "error",
    article_id: str = "",
    section: str = "",
    sub_section: str = "",
) -> None:
    LOG_ROWS.append(
        {
            "article_id": article_id,
            "url": url,
            "status": status,
            "reason": reason,
            "section": section,
            "sub_section": sub_section,
            "occurred_at": now_iso(),
        }
    )


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
    """Check the generic robots.txt block.

    Python's RobotFileParser can treat later bot-specific blocks too broadly for
    this site. For this crawler we only apply the User-agent: * block and keep
    the request delay conservative.
    """
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

        path = parsed.path
        return not any(path.startswith(rule) for rule in disallow_rules)
    except Exception as exc:
        add_log(url, f"robots.txt 확인 실패, 수집 계속 진행: {exc}", "warning")
        return True


def fetch_html(url: str, session: Optional[requests.Session] = None) -> str:
    if not can_fetch(url):
        raise RuntimeError(f"robots.txt disallows fetching: {url}")

    session = session or build_session()
    response = session.get(url, timeout=20)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def fetch_html_with_playwright(url: str) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeError(f"Playwright import 실패: {exc}") from exc

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR")
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()
        return html


def normalize_url(href: str, base_url: str = BASE_URL) -> str:
    return urljoin(base_url, href.split("#")[0])


def infer_section_from_url(url: str) -> Optional[str]:
    match = re.search(r"/arti/([^/?#]+)", url)
    return match.group(1) if match else None


def infer_fallback_section_name(section_url: str) -> str:
    slug = infer_section_from_url(section_url)
    return SECTION_NAME_BY_SLUG.get(slug or "", slug or "unknown")


def extract_article_items_from_soup(soup: BeautifulSoup, base_url: str) -> List[Dict[str, str]]:
    raw_items: List[Dict[str, str]] = []
    article_pattern = re.compile(r"/arti/[^\"'?#]+/\d+\.html$")

    list_items = soup.select('div[class*="section_left"] li[class*="ArticleList_item"]')
    search_roots = list_items if list_items else [soup]

    for root in search_roots:
        for a_tag in root.select('a[href*="/arti/"]'):
            href = a_tag.get("href", "")
            absolute_url = normalize_url(href, base_url)
            parsed_path = urlparse(absolute_url).path
            if not article_pattern.search(parsed_path):
                continue

            section_name = None
            parent = a_tag.parent
            for _ in range(4):
                if not parent:
                    break
                section_link = parent.select_one('a[href^="/arti/"]:not([href$=".html"])')
                if section_link:
                    section_name = section_link.get_text(" ", strip=True) or infer_section_from_url(section_link.get("href", ""))
                    break
                parent = parent.parent

            raw_items.append(
                {
                    "url": absolute_url,
                    "section_name": section_name or infer_section_from_url(absolute_url) or "unknown",
                }
            )

    seen = set()
    unique_items = []
    for item in raw_items:
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        unique_items.append(item)
    return unique_items


def find_page_button(page, page_number: int):
    title_locator = page.locator(f'button[title="{page_number}페이지로 이동"]')
    if title_locator.count() > 0:
        return title_locator.first

    exact_text_locator = page.locator("button").filter(has_text=str(page_number))
    for idx in range(exact_text_locator.count()):
        candidate = exact_text_locator.nth(idx)
        if candidate.inner_text(timeout=1000).strip() == str(page_number):
            return candidate

    pagination = page.locator('div[class*="pagination"], div[class*="Pagination"]')
    if pagination.count() > 0:
        buttons = pagination.first.locator("button")
        for idx in range(buttons.count()):
            candidate = buttons.nth(idx)
            if candidate.inner_text(timeout=1000).strip() == str(page_number):
                return candidate

    return None


def page_article_signature(page) -> str:
    return page.eval_on_selector_all(
        'div[class*="section_left"] li[class*="ArticleList_item"] a[href*="/arti/"]',
        """links => links.map(link => link.getAttribute('href')).filter(Boolean).join('|')""",
    )


def collect_article_links(section_url, max_pages=1, limit=None, test=False, start_page=1):
    """Collect article detail links from one Hani section/list page, optionally paginated."""
    if test:
        max_pages = 1
        limit = 5
        start_page = 1

    max_pages = max(1, min(int(max_pages or 1), 5))
    start_page = max(1, min(int(start_page or 1), max_pages))
    raw_count = 0
    visited_pages = 0
    page_counts: Dict[int, int] = {}
    unique_by_url: Dict[str, Dict[str, str]] = {}
    collect_article_links.requested_max_pages = max_pages
    collect_article_links.last_visited_pages = 0
    collect_article_links.last_page_counts = {}
    collect_article_links.last_raw_count = 0
    collect_article_links.last_unique_count = 0
    collect_article_links.requested_start_page = start_page

    def add_page_items(page_number: int, html: str) -> None:
        nonlocal raw_count
        soup = make_soup(html)
        items = extract_article_items_from_soup(soup, section_url)
        raw_count += len(items)
        page_counts[page_number] = len(items)
        for item in items:
            if item["url"] in unique_by_url:
                continue
            unique_by_url[item["url"]] = item
            if limit and len(unique_by_url) >= limit:
                break

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        if max_pages > 1:
            raise RuntimeError(f"Playwright import 실패: {exc}") from exc

        session = build_session()
        html = fetch_html(section_url, session=session)
        if start_page <= 1:
            add_page_items(1, html)
            visited_pages = 1
        collect_article_links.last_raw_count = raw_count
        collect_article_links.last_unique_count = len(unique_by_url)
        collect_article_links.last_visited_pages = visited_pages
        collect_article_links.last_page_counts = page_counts
        collect_article_links.requested_max_pages = max_pages
        return list(unique_by_url.values())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR")
        page.goto(section_url, wait_until="networkidle", timeout=30000)
        page.wait_for_selector('a[href*="/arti/"]', timeout=15000)

        for page_number in range(1, max_pages + 1):
            if page_number > 1:
                before_signature = page_article_signature(page)
                button = find_page_button(page, page_number)
                if button is None:
                    add_log(section_url, f"{page_number}페이지 버튼을 찾지 못함", "error")
                    continue
                try:
                    button.click(timeout=10000)
                    try:
                        page.wait_for_function(
                            """
                            oldSignature => Array.from(document.querySelectorAll(
                              'div[class*="section_left"] li[class*="ArticleList_item"] a[href*="/arti/"]'
                            )).map(link => link.getAttribute('href')).filter(Boolean).join('|') !== oldSignature
                            """,
                            arg=before_signature,
                            timeout=10000,
                        )
                    except PlaywrightTimeoutError:
                        page.wait_for_load_state("networkidle", timeout=10000)
                    page.wait_for_selector('div[class*="section_left"] a[href*="/arti/"]', timeout=15000)
                except Exception as exc:
                    add_log(section_url, f"{page_number}페이지 이동 실패: {exc}", "error")
                    continue

            if page_number >= start_page:
                visited_pages += 1
                add_page_items(page_number, page.content())
                if limit and len(unique_by_url) >= limit:
                    break

        browser.close()

    collect_article_links.last_raw_count = raw_count
    collect_article_links.last_unique_count = len(unique_by_url)
    collect_article_links.last_visited_pages = visited_pages
    collect_article_links.last_page_counts = page_counts
    collect_article_links.requested_max_pages = max_pages
    return list(unique_by_url.values())


collect_article_links.last_raw_count = 0
collect_article_links.last_unique_count = 0
collect_article_links.last_visited_pages = 0
collect_article_links.last_page_counts = {}
collect_article_links.requested_max_pages = 1
collect_article_links.requested_start_page = 1


def normalize_section_folder(section: str) -> str:
    section = (section or "unknown").strip()
    if section in {"기술/과학", "기술 과학"}:
        return "기술과학"
    return re.sub(r'[<>:"/\\|?*]', "", section) or "unknown"


def extract_sections_from_breadcrumb(soup, fallback_section=None):
    candidates = []

    for container in soup.find_all(["nav", "div", "section", "ul"]):
        links = container.find_all("a", href=lambda href: href and href.startswith("/arti/"))
        non_article_links = [
            link for link in links if not re.search(r"/\d+\.html$", link.get("href", ""))
        ]
        if non_article_links:
            class_text = " ".join(container.get("class", [])).lower()
            score = 2 if "breadcrumb" in class_text else 1
            candidates.append((score, non_article_links))

    if candidates:
        candidates.sort(key=lambda item: item[0], reverse=True)
        link_texts = [link.get_text(" ", strip=True) for link in candidates[0][1]]
        link_texts = [text for text in link_texts if text]
        if link_texts:
            return {
                "section": link_texts[0],
                "sub_section": link_texts[1] if len(link_texts) > 1 else "unknown",
            }

    return {"section": fallback_section or "unknown", "sub_section": "unknown"}


def extract_section_from_breadcrumb(soup, fallback_section=None):
    return extract_sections_from_breadcrumb(soup, fallback_section)["section"]


def extract_next_data(soup: BeautifulSoup) -> Dict:
    script = soup.find("script", id="__NEXT_DATA__", type="application/json")
    if not script or not script.string:
        return {}
    try:
        data = json.loads(script.string)
        return data.get("props", {}).get("pageProps", {}).get("article", {}) or {}
    except Exception:
        return {}


def extract_article_id(article_url: str, soup: Optional[BeautifulSoup] = None) -> str:
    meta_id = soup.select_one('meta[name="h:article_id"]') if soup else None
    if meta_id and meta_id.get("content"):
        return meta_id["content"].strip()

    match = re.search(r"/(\d+)\.html(?:$|[?#])", article_url)
    if match:
        return match.group(1)

    return hashlib.sha256(article_url.encode("utf-8")).hexdigest()[:16]


def normalize_date(value: Optional[str]) -> str:
    if not value:
        return ""
    value = value.strip()

    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", value)
    if iso_match:
        return "-".join(iso_match.groups())

    compact_match = re.search(r"(\d{4})(\d{2})(\d{2})", value)
    if compact_match:
        return "-".join(compact_match.groups())

    korean_match = re.search(r"(\d{4})[.년\-/ ]+(\d{1,2})[.월\-/ ]+(\d{1,2})", value)
    if korean_match:
        year, month, day = korean_match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    return value[:10]


def clean_article_text(text):
    if not text:
        return ""

    text = re.sub(r"\[%%[^%]+%%\]", " ", text)
    text = make_soup(text).get_text("\n", strip=True)
    text = re.sub(r"\s+", " ", text)

    remove_patterns = [
        r"^.*?기자\s+[A-Za-z0-9._%+-]+@hani\.co\.kr$",
        r"^.*?기자$",
        r"^구독$",
        r"^광고$",
        r"^관련기사.*$",
        r"^한겨레.*?구독.*$",
        r"^©.*$",
        r"^무단 전재.*$",
        r"^AI 학습 및 활용 금지.*$",
        r"^기사 읽어드립니다.*$",
    ]

    cleaned_parts = []
    for part in re.split(r"(?<=[.!?다요죠)])\s+", text):
        sentence = part.strip()
        if not sentence:
            continue
        if any(re.search(pattern, sentence) for pattern in remove_patterns):
            continue
        cleaned_parts.append(sentence)

    return re.sub(r"\s+", " ", " ".join(cleaned_parts)).strip()


def clean_paragraph_text(text: str) -> str:
    return clean_article_text(text)


def split_korean_sentences(paragraph: str) -> List[str]:
    paragraph = re.sub(r"\s+", " ", paragraph or "").strip()
    if not paragraph:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", paragraph) if part.strip()]


def format_article_text_for_txt(paragraphs: List[str]) -> str:
    formatted = []
    for paragraph in paragraphs:
        sentences = split_korean_sentences(paragraph)
        if sentences:
            formatted.append("\n".join(sentences))
    return "\n\n".join(formatted).strip() + "\n"


def extract_body_paragraphs(soup: BeautifulSoup, next_article: Dict) -> List[str]:
    content_html = next_article.get("content")
    if content_html:
        content_soup = make_soup(content_html)
        paragraphs = []
        for removable in content_soup.select("figure, figcaption, picture, img, script, style, noscript, iframe, [class*='Ad'], [class*='ad']"):
            removable.decompose()
        p_tags = content_soup.select("p")
        if p_tags:
            for p_tag in p_tags:
                txt = clean_paragraph_text(p_tag.get_text(" ", strip=True))
                if txt:
                    paragraphs.append(txt)
        else:
            txt = clean_paragraph_text(content_soup.get_text(" ", strip=True))
            if txt:
                paragraphs.append(txt)
        if paragraphs:
            return paragraphs

    article_node = soup.select_one(".article-text")
    if not article_node:
        article_node = soup.select_one("article")
    if not article_node:
        return []

    for removable in article_node.select(
        "figure, figcaption, picture, img, script, style, noscript, iframe, "
        "[class*='Ad'], [class*='ad'], [class*='caption'], [class*='Caption'], "
        "[class*='Related'], [class*='related'], [class*='Audio'], [class*='audio']"
    ):
        removable.decompose()

    paragraphs = []
    p_tags = article_node.select("p")
    if p_tags:
        for p_tag in p_tags:
            txt = p_tag.get_text(" ", strip=True)
            if txt:
                cleaned = clean_paragraph_text(txt)
                if cleaned:
                    paragraphs.append(cleaned)
    else:
        cleaned = clean_paragraph_text(article_node.get_text(" ", strip=True))
        if cleaned:
            paragraphs.append(cleaned)

    return paragraphs


def extract_body_text(soup: BeautifulSoup, next_article: Dict) -> str:
    return " ".join(extract_body_paragraphs(soup, next_article)).strip()


def should_exclude_article(section: str, sub_section: str, title: str, article_url: str) -> Optional[str]:
    target = " ".join([section or "", sub_section or "", title or "", article_url or ""])
    normalized = re.sub(r"\s+", "", target)
    if "정치BAR" in normalized:
        return "정치 BAR 카테고리 제외"
    if (section or "").strip() == "사회":
        excluded_society_sub_sections = {"궂긴소식", "인사", "엔지오", "종교"}
        normalized_sub_section = re.sub(r"\s+", "", sub_section or "")
        if any(re.sub(r"\s+", "", name) in normalized_sub_section for name in excluded_society_sub_sections):
            return f"사회 제외 상세 카테고리: {sub_section}"
    if (section or "").strip() == "경제":
        normalized_sub_section = re.sub(r"\s+", "", sub_section or "")
        if "기업PR" in normalized_sub_section:
            return f"경제 제외 상세 카테고리: {sub_section}"
    if any(keyword in target for keyword in ["사설", "칼럼", "논설", "기고"]):
        return "사설·칼럼 성격 콘텐츠 제외"
    return None


def parse_article(article_url, section_name=None):
    session = build_session()
    html = fetch_html(article_url, session=session)
    soup = make_soup(html)
    next_article = extract_next_data(soup)

    title = ""
    title_tag = soup.select_one("h1, h2, h3")
    meta_title = soup.select_one('meta[property="og:title"], meta[name="h:title"]')
    if next_article.get("title"):
        title = next_article["title"].strip()
    elif meta_title and meta_title.get("content"):
        title = meta_title["content"].strip()
    elif title_tag:
        title = title_tag.get_text(" ", strip=True)

    published_date = ""
    for selector in [
        'meta[name="h:published_time"]',
        'meta[property="article:published_time"]',
        'meta[name="publish"]',
    ]:
        meta = soup.select_one(selector)
        if meta and meta.get("content"):
            published_date = normalize_date(meta["content"])
            break
    if not published_date:
        published_date = normalize_date(next_article.get("createDate") or next_article.get("updateDate"))

    sections = extract_sections_from_breadcrumb(soup, fallback_section=section_name)
    section = sections["section"]
    sub_section = sections["sub_section"]
    if section == "unknown" and next_article.get("section", {}).get("label"):
        section = next_article["section"]["label"]
    if sub_section == "unknown" and next_article.get("subSection", {}).get("label"):
        sub_section = next_article["subSection"]["label"]

    exclude_reason = should_exclude_article(section, sub_section, title, article_url)
    if exclude_reason:
        article_id = extract_article_id(article_url, soup)
        raise ExcludedArticle(exclude_reason, article_id, section, sub_section)

    body_paragraphs = extract_body_paragraphs(soup, next_article)
    body_text = " ".join(body_paragraphs).strip()

    if len(body_text) < MIN_BODY_LENGTH:
        try:
            fallback_html = fetch_html_with_playwright(article_url)
            fallback_soup = make_soup(fallback_html)
            fallback_next_article = extract_next_data(fallback_soup)
            fallback_paragraphs = extract_body_paragraphs(fallback_soup, fallback_next_article)
            fallback_body = " ".join(fallback_paragraphs).strip()
            if len(fallback_body) > len(body_text):
                soup = fallback_soup
                next_article = fallback_next_article
                body_paragraphs = fallback_paragraphs
                body_text = fallback_body
                sections = extract_sections_from_breadcrumb(soup, fallback_section=section)
                section = sections["section"]
                sub_section = sections["sub_section"]
        except Exception as exc:
            add_log(article_url, f"Playwright fallback 실패: {exc}", "warning")

    article_id = extract_article_id(article_url, soup)

    if len(body_text) < MIN_BODY_LENGTH:
        raise ValueError(f"본문이 비어 있거나 너무 짧음: {len(body_text)}자")

    return {
        "article_id": article_id,
        "title": title,
        "published_date": published_date,
        "section": section or section_name or "unknown",
        "sub_section": sub_section or "unknown",
        "body_text": body_text,
        "txt_text": format_article_text_for_txt(body_paragraphs),
        "url": article_url,
    }


class ExcludedArticle(Exception):
    def __init__(self, reason: str, article_id: str = "", section: str = "", sub_section: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.article_id = article_id
        self.section = section
        self.sub_section = sub_section


def save_article_txt(article_id, body_text, section="unknown"):
    ensure_dirs()
    section_dir = RAW_TXT_DIR / normalize_section_folder(section)
    section_dir.mkdir(parents=True, exist_ok=True)
    txt_path = section_dir / f"{article_id}.txt"
    txt_path.write_text(body_text, encoding="utf-8")
    return txt_path


def save_news_raw_csv(records):
    ensure_dirs()
    columns = ["article_id", "title", "published_date", "section", "body_text", "url"]
    with NEWS_RAW_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for record in records:
            writer.writerow({column: record.get(column, "") for column in columns})
    return NEWS_RAW_CSV


def load_existing_news_raw_csv() -> List[Dict[str, str]]:
    if not NEWS_RAW_CSV.exists():
        return []
    with NEWS_RAW_CSV.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def merge_records_by_url(existing_records: List[Dict[str, str]], new_records: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {}
    for record in existing_records:
        url = record.get("url", "")
        if url:
            merged[url] = record
    for record in new_records:
        url = record.get("url", "")
        if url:
            merged[url] = record
    return list(merged.values())


def save_log_csv() -> Path:
    ensure_dirs()
    columns = ["article_id", "url", "status", "reason", "section", "sub_section", "occurred_at"]
    with NEWS_LOG_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in LOG_ROWS:
            writer.writerow(row)
    return NEWS_LOG_CSV


def print_summary(records: List[Dict[str, str]], txt_count: int) -> None:
    failed_count = len([row for row in LOG_ROWS if row.get("status") == "error"])
    excluded_count = len([row for row in LOG_ROWS if row.get("status") == "excluded"])
    section_counter = Counter(record["section"] for record in records)
    dates = sorted(record["published_date"] for record in records if record.get("published_date"))
    date_range = f"{dates[0]} ~ {dates[-1]}" if dates else "unknown"

    print(f"요청한 max_pages: {collect_article_links.requested_max_pages}")
    print(f"요청한 start_page: {collect_article_links.requested_start_page}")
    print(f"실제 방문한 페이지 수: {collect_article_links.last_visited_pages}")
    print("페이지별 수집 기사 URL 수:")
    for page_number, count in sorted(collect_article_links.last_page_counts.items()):
        print(f"  - {page_number}페이지: {count}")
    print(f"수집한 기사 URL 수: {collect_article_links.last_raw_count}")
    print(f"중복 제거 후 기사 URL 수: {collect_article_links.last_unique_count}")
    print(f"본문 파싱 성공 수: {len(records)}")
    print(f"본문 파싱 실패 수: {failed_count}")
    print(f"제외 기사 수: {excluded_count}")
    print("섹션별 기사 수:")
    for section, count in sorted(section_counter.items()):
        print(f"  - {section}: {count}")
    print(f"날짜 범위: {date_range}")
    print(f"txt 저장 성공 수: {txt_count}")
    print(f"CSV 저장 경로: {NEWS_RAW_CSV}")
    print(f"로그 저장 경로: {NEWS_LOG_CSV}")
    print(f"txt 파일 저장 개수: {txt_count}")


def main():
    parser = argparse.ArgumentParser(description="한겨레 1페이지 기사 본문 수집기")
    parser.add_argument(
        "section_url_arg",
        nargs="?",
        default=None,
        help="수집할 한겨레 섹션 1페이지 URL",
    )
    parser.add_argument("--section-url", dest="section_url", default=None, help="수집할 한겨레 섹션 URL")
    parser.add_argument("--section-name", default=None, help="fallback 섹션명")
    parser.add_argument("--max-pages", type=int, default=1, help="수집할 페이지 수. 현재는 1~5 숫자 버튼만 지원")
    parser.add_argument("--start-page", type=int, default=1, help="수집을 시작할 페이지 번호")
    parser.add_argument("--limit", type=int, default=None, help="중복 제거 기준 최대 기사 수")
    parser.add_argument("--append-existing", action="store_true", help="기존 news_raw.csv를 유지하고 새 결과를 URL 기준으로 병합")
    parser.add_argument("--test", action="store_true", help="기사 5개만 수집")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS, help="요청 간 딜레이(초)")
    args = parser.parse_args()

    ensure_dirs()
    records: List[Dict[str, str]] = []
    txt_count = 0
    section_url = args.section_url or args.section_url_arg or "https://www.hani.co.kr/arti/politics"
    fallback_section = args.section_name or infer_fallback_section_name(section_url)

    try:
        links = collect_article_links(
            section_url,
            max_pages=args.max_pages,
            limit=args.limit,
            test=args.test,
            start_page=args.start_page,
        )
    except Exception as exc:
        add_log(section_url, f"목록 페이지 수집 실패: {exc}")
        save_log_csv()
        print_summary(records, txt_count)
        return

    for item in links:
        article_url = item["url"]
        try:
            time.sleep(max(args.delay, 0))
            record = parse_article(article_url, section_name=fallback_section or item.get("section_name"))
            save_article_txt(record["article_id"], record.get("txt_text") or record["body_text"], record["section"])
            records.append(record)
            txt_count += 1
        except ExcludedArticle as exc:
            add_log(
                article_url,
                exc.reason,
                "excluded",
                article_id=exc.article_id,
                section=exc.section,
                sub_section=exc.sub_section,
            )
            continue
        except Exception as exc:
            add_log(article_url, str(exc))
            continue

    try:
        records_to_save = records
        if (args.start_page > 1 or args.append_existing) and not args.test:
            existing_records = load_existing_news_raw_csv()
            records_to_save = merge_records_by_url(existing_records, records)
        save_news_raw_csv(records_to_save)
    except PermissionError as exc:
        add_log(str(NEWS_RAW_CSV), f"CSV 저장 실패: 파일이 다른 프로그램에서 사용 중입니다. {exc}", "error")
    save_log_csv()
    print_summary(records, txt_count)


if __name__ == "__main__":
    main()
