"""
매체 공지사항 크롤러

사용법:
    pip install requests
    python crawler.py

- SOURCES 리스트에 있는 URL들을 순서대로 가져와서 파싱
- 이전 실행 때 본 적 없는 id는 새 글로 표시
- data/seen_ids.json    : 지금까지 본 공지 id 저장 (중복 알림 방지용)
- data/notices.json      : 대시보드(dashboard.html)가 읽어가는 최종 데이터

주의: 이 스크립트는 로컬/서버 등 실제 인터넷이 되는 환경에서 실행해야 합니다.
"""
import json
import re
from pathlib import Path
from datetime import datetime

import requests

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
SEEN_IDS_PATH = DATA_DIR / "seen_ids.json"
NOTICES_PATH = DATA_DIR / "notices.json"

# 매체별 소스. 이름과 URL만 추가하면 계속 확장 가능.
SOURCES = [
    {"platform": "네이버 GFA", "url": "https://ads.naver.com/notice?categoryId=148&page=1"},
    # {"platform": "NOSP", "url": "..."},  # URL 확인되면 추가
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


def extract_notices(raw_html: str):
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
            "url": "https://ads.naver.com" + _unescape(m.group("url")),
        })
    return notices


def load_seen_ids() -> dict:
    if SEEN_IDS_PATH.exists():
        return json.loads(SEEN_IDS_PATH.read_text(encoding="utf-8"))
    return {}


def save_seen_ids(seen: dict):
    SEEN_IDS_PATH.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")


def fetch(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                      " (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def run():
    seen_ids = load_seen_ids()  # {platform: [id, id, ...]}
    all_notices = []
    new_count_total = 0

    for source in SOURCES:
        platform = source["platform"]
        try:
            raw = fetch(source["url"])
        except requests.RequestException as e:
            print(f"[에러] {platform} 요청 실패: {e}")
            continue

        notices = extract_notices(raw)
        platform_seen = set(seen_ids.get(platform, []))

        for n in notices:
            n["platform"] = platform
            n["is_new"] = n["id"] not in platform_seen
            if n["is_new"]:
                new_count_total += 1
            all_notices.append(n)

        seen_ids[platform] = list({n["id"] for n in notices} | platform_seen)
        print(f"[{platform}] {len(notices)}건 수집, 신규 {sum(1 for n in notices if n['is_new'])}건")

    all_notices.sort(key=lambda n: n["date"], reverse=True)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "new_count": new_count_total,
        "notices": all_notices,
    }
    NOTICES_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    save_seen_ids(seen_ids)
    print(f"\n총 {len(all_notices)}건 저장 완료 -> {NOTICES_PATH}")


if __name__ == "__main__":
    run()