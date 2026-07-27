"""
매체 공지사항 크롤러

사용법:
    pip install requests
    python crawler.py

- SOURCES 리스트에 있는 URL들을 순서대로 가져와서 파싱
- "새 글" 여부는 네이버가 자체적으로 계산해서 내려주는 isNew 값을 그대로 사용
  (우리 쪽에서 "처음 봤는지"로 판단하지 않음 -> 크롤러를 며칠 만에 돌려도 오래된 글이
   갑자기 무더기로 NEW 처리되는 문제가 없음)
- data/notices.json      : 대시보드(dashboard.html)가 읽어가는 최종 데이터

주의: 이 스크립트는 로컬/서버 등 실제 인터넷이 되는 환경에서 실행해야 합니다.
"""
import json
import re
from pathlib import Path
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
NOTICES_PATH = DATA_DIR / "notices.json"

# 며칠 이내 발행된 글까지 NEW로 볼지 (RSS 소스처럼 자체 NEW 표시가 없는 경우에 사용)
NEW_WINDOW_DAYS = 5

# 매체별 소스. type: "gfa_json" (네이버 GFA처럼 페이지에 JSON이 박혀있는 경우) / "rss" (표준 RSS 피드)
SOURCES = [
    {"platform": "네이버 GFA", "type": "gfa_json", "url": "https://ads.naver.com/notice?categoryId=148&page=1"},
    {"platform": "메타 for Business", "type": "rss", "url": "https://en-gb.facebook.com/business/news/rss"},
    # {"platform": "NOSP", "type": "gfa_json", "url": "..."},  # URL 확인되면 추가
]

NOTICE_PATTERN = re.compile(
    r'\\?"category\\?":\{.*?\\?"categoryName\\?":\\?"(?P<category>[^"\\]*)\\?".*?\}'
    r'.*?\\?"hasAttachment\\?":(?:true|false),\\?"id\\?":(?P<id>\d+)'
    r'.*?\\?"isNew\\?":(?P<is_new>true|false)'
    r'.*?\\?"isPinned\\?":(?P<is_pinned>true|false)'
    r'.*?\\?"title\\?":\\?"(?P<title>.*?)\\?",\\?"viewUrl\\?":\\?"(?P<url>[^"\\]*)\\?"'
    r'.*?\\?"date\\?":\\?"(?P<date>\d{4}-\d{2}-\d{2})\\?"\}',
    re.DOTALL
)


def _unescape(s: str) -> str:
    return (s.replace('\\"', '"')
             .replace('\\u0026', '&')
             .replace('\\u003c', '<')
             .replace('\\u003e', '>')
             .replace('\\/', '/')
             .replace('\\\\', '\\'))


def extract_gfa_notices(raw_html: str):
    notices = []
    seen_in_page = set()
    for m in NOTICE_PATTERN.finditer(raw_html):
        notice_id = int(m.group("id"))
        if notice_id in seen_in_page:
            continue
        seen_in_page.add(notice_id)
        notices.append({
            "id": notice_id,
            "title": _unescape(m.group("title")),
            "category": _unescape(m.group("category")),
            "date": m.group("date"),
            "is_pinned": m.group("is_pinned") == "true",
            "is_new": m.group("is_new") == "true",
            "url": "https://ads.naver.com" + _unescape(m.group("url")),
        })
    return notices


def extract_rss_notices(raw_xml: str):
    """표준 RSS 2.0 피드 파싱 (예: 메타 for Business). isNew 개념이 없어서
    최근 NEW_WINDOW_DAYS일 이내 발행된 글만 NEW로 표시한다."""
    root = ElementTree.fromstring(raw_xml)
    now_kst = datetime.now(KST)
    notices = []

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        category = (item.findtext("category") or "").strip()
        pub_date_raw = item.findtext("pubDate")

        if pub_date_raw:
            pub_dt = parsedate_to_datetime(pub_date_raw).astimezone(KST)
            date_str = pub_dt.strftime("%Y-%m-%d")
            is_new = (now_kst - pub_dt) <= timedelta(days=NEW_WINDOW_DAYS)
        else:
            date_str = ""
            is_new = False

        # link를 안정적인 id로 사용 (RSS에는 별도 숫자 id가 없음)
        notice_id = link or title

        notices.append({
            "id": notice_id,
            "title": title,
            "category": category,
            "date": date_str,
            "is_pinned": False,
            "is_new": is_new,
            "url": link,
        })
    return notices


def fetch(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                      " (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def run():
    crawled_platforms = {s["platform"] for s in SOURCES}
    fresh_notices = []

    for source in SOURCES:
        platform = source["platform"]
        source_type = source["type"]
        try:
            raw = fetch(source["url"])
        except requests.RequestException as e:
            print(f"[에러] {platform} 요청 실패: {e}")
            continue

        try:
            if source_type == "rss":
                notices = extract_rss_notices(raw)
            else:
                notices = extract_gfa_notices(raw)
        except ElementTree.ParseError as e:
            print(f"[에러] {platform} 파싱 실패 (RSS XML이 아닌 것 같아요): {e}")
            continue

        for n in notices:
            n["platform"] = platform
        fresh_notices.extend(notices)
        print(f"[{platform}] {len(notices)}건 수집, 신규(NEW 배지) {sum(1 for n in notices if n['is_new'])}건")

    # notices.json에 다른 방식(예: merge_kakao.py)으로 들어간 다른 플랫폼 데이터는 그대로 유지
    existing = {}
    if NOTICES_PATH.exists():
        existing = json.loads(NOTICES_PATH.read_text(encoding="utf-8"))
    kept = [n for n in existing.get("notices", []) if n.get("platform") not in crawled_platforms]

    all_notices = kept + fresh_notices
    all_notices.sort(key=lambda n: n["date"], reverse=True)

    output = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "new_count": sum(1 for n in all_notices if n["is_new"]),
        "notices": all_notices,
    }
    NOTICES_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n총 {len(all_notices)}건 저장 완료 -> {NOTICES_PATH}")


if __name__ == "__main__":
    run()