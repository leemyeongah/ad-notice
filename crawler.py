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

# 매체별 소스. type: "gfa_json" (네이버 GFA처럼 페이지에 JSON이 박혀있는 경우) /
# "rss" (표준 RSS 피드) / "nasmedia" (나스미디어 블로그 post-item 목록)
# 메타(Facebook)는 자동 요청을 막아서(400 에러) 여기 넣지 않음 -> merge_meta.py로 반자동 처리
SOURCES = [
    {"platform": "네이버 GFA", "type": "gfa_json", "url": "https://ads.naver.com/notice?categoryId=148&page=1"},
    {"platform": "나스미디어 뉴스클리핑", "type": "nasmedia", "category_label": "뉴스클리핑", "highlight_top_n": 3,
     "url": "https://blog.nasmedia.co.kr/category/%EB%94%94%EC%A7%80%ED%84%B8%20%EB%AF%B8%EB%94%94%EC%96%B4%20%EC%9D%B4%EC%8A%88/%EB%89%B4%EC%8A%A4%ED%81%B4%EB%A6%AC%ED%95%91"},
    {"platform": "나스미디어 광고상품업데이트", "type": "nasmedia", "category_label": "광고 상품 업데이트",
     "url": "https://blog.nasmedia.co.kr/category/%EB%94%94%EC%A7%80%ED%84%B8%20%EB%AF%B8%EB%94%94%EC%96%B4%20%EC%9D%B4%EC%8A%88/%EA%B4%91%EA%B3%A0%20%EC%83%81%ED%92%88%20%EC%97%85%EB%8D%B0%EC%9D%B4%ED%8A%B8"},
    # 토스애즈는 페이지에 직접 API가 안 박혀있고 자바스크립트로 불러오지만, 그 API 자체는 인증 없이 열려있어서 바로 호출
    # (workspace_id=35, category_id=223 = "시스템 공지" 카테고리. 231은 FAQ라서 제외)
    {"platform": "토스애즈", "type": "toss_faq",
     "url": "https://faq-editor-api.toss.im/api/v1/workspaces/35/faq/?with_deleted=false&page_size=20&order_by=-is_pinned,-created_time&page=1&category_id=223"},
    # {"platform": "NOSP", "type": "gfa_json", "url": "..."},  # URL 확인되면 추가
]

NASMEDIA_POST_ITEM = re.compile(
    r'<div class="post-item">\s*<a href="(?P<href>/entry/[^"]+)".*?'
    r'<span class="title">(?P<title>[^<]+)</span>.*?'
    r'<span class="excerpt">(?P<excerpt>.*?)</span>.*?'
    r'<span class="date">(?P<date>[^<]+)</span>',
    re.DOTALL
)
NASMEDIA_NEW_WINDOW_DAYS = 7

# 광고상품업데이트 등에서 본문 안에 언급된 매체를 자동 태깅하기 위한 키워드 목록
# (등장 빈도가 흔한 매체 위주, 길이가 긴 이름을 먼저 매칭해서 부분 중복 방지)
KNOWN_PLATFORMS = [
    "인스타그램", "유튜브", "챗GPT", "오픈AI", "네이버지도", "네이버페이", "네이버",
    "카카오톡", "카카오페이", "카카오", "당근", "메타", "구글", "토스", "틱톡",
    "쿠팡", "배민", "링크드인", "스레드", "X", "OTT",
]


def _clean_html_text(raw: str) -> str:
    """excerpt/title 안의 HTML 엔티티를 풀고 남은 태그를 제거."""
    text = re.sub(r'<[^>]+>', '', raw)
    replacements = {
        '&middot;': '·', '&hellip;': '…', '&lsquo;': '‘', '&rsquo;': '’',
        '&ldquo;': '“', '&rdquo;': '”', '&amp;': '&', '&nbsp;': ' ',
        '&quot;': '"', '&#39;': "'", '&lt;': '<', '&gt;': '>',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    return text.strip()


def _clean_html_preserve_bold(raw: str) -> str:
    """_clean_html_text와 같은 정리를 하되, <b>/<strong>로 감싼 부분(원문에서 실제로
    굵게 강조된 헤드라인)만 <mark>...</mark>로 남겨서 나중에 대시보드에서 하이라이트로 보여준다."""
    text = re.sub(r'<(?:b|strong)(?:\s[^>]*)?>', '\x01', raw, flags=re.IGNORECASE)
    text = re.sub(r'</(?:b|strong)>', '\x02', text, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    replacements = {
        '&middot;': '·', '&hellip;': '…', '&lsquo;': '‘', '&rsquo;': '’',
        '&ldquo;': '“', '&rdquo;': '”', '&amp;': '&', '&nbsp;': ' ',
        '&quot;': '"', '&#39;': "'", '&lt;': '<', '&gt;': '>',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = text.replace('\x01', '<mark>').replace('\x02', '</mark>')
    return re.sub(r'\s+', ' ', text).strip()


def fetch_highlighted_excerpt(entry_url: str, max_len: int = 550) -> str:
    """뉴스클리핑 개별 글 페이지에서 실제로 <b> 처리된 헤드라인을 살린 요약을 만든다.
    카테고리 목록 페이지의 excerpt는 서식이 다 빠진 평문이라 여기서 따로 만든다.
    실패해도 조용히 빈 문자열을 돌려주고, 호출부에서는 원래 평문 excerpt를 그대로 쓴다."""
    try:
        raw_html = fetch(entry_url)
    except requests.RequestException:
        return ""

    marker_idx = raw_html.find('id="article-view"')
    if marker_idx == -1:
        return ""
    tag_start = raw_html.rfind('<', 0, marker_idx)
    if tag_start == -1:
        return ""
    chunk = raw_html[tag_start:tag_start + 20000]
    chunk = chunk[:chunk.rfind('>') + 1]

    text = _clean_html_preserve_bold(chunk)
    text = re.sub(r'\s*#디지털미디어\s*', ' ', text)
    text = re.sub(r'(?:#\S+\s*){2,}(?=📢)', '', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()

    if len(text) > max_len:
        text = text[:max_len]
        if text.count('<mark>') > text.count('</mark>'):
            text += '</mark>'
        text += '…'
    return text


def _detect_platforms(text: str):
    found = []
    for name in KNOWN_PLATFORMS:
        if name in text and name not in found:
            found.append(name)
    return found

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


def extract_nasmedia_notices(raw_html: str, category_label: str = "", highlight_top_n: int = 0):
    """나스미디어 블로그 카테고리 목록 페이지 파싱 (뉴스클리핑/광고 상품 업데이트 등 공통).
    URL 슬러그 형식이 카테고리마다 달라서(YYYYMMDD-... 나 YYYYMM... 등) 슬러그 날짜는 안 쓰고,
    화면에 보이는 게시일(meta date)만 date/NEW 판정 기준으로 사용.

    highlight_top_n > 0이면 최신 글부터 그만큼 개별 글 페이지를 추가로 열어서
    실제 굵게 강조된 헤드라인이 살아있는 excerpt로 바꿔치기한다(대시보드에 최근 몇 건만 보여주므로
    전체 목록을 다 열어볼 필요는 없음)."""
    notices = []
    now_kst = datetime.now(KST)

    for m in NASMEDIA_POST_ITEM.finditer(raw_html):
        raw_date = m.group("date").strip().rstrip('.')
        date_iso = ""
        is_new = False
        try:
            y, mo, d = [int(p.strip()) for p in raw_date.split('.')]
            meta_dt = datetime(y, mo, d, tzinfo=KST)
            date_iso = meta_dt.strftime("%Y-%m-%d")
            is_new = (now_kst - meta_dt) <= timedelta(days=NASMEDIA_NEW_WINDOW_DAYS)
        except (ValueError, IndexError):
            pass

        title_clean = _clean_html_text(m.group("title"))
        excerpt_clean = _clean_html_text(m.group("excerpt"))
        platforms = _detect_platforms(title_clean + " " + excerpt_clean)

        # 나스미디어 글머리에 흔히 붙는 해시태그 무더기(예: "#디지털미디어", "#네이버 #메타 #당근📢") 제거
        excerpt_clean = excerpt_clean.replace('#디지털미디어', '')
        excerpt_clean = re.sub(r'(?:#\S+\s*){2,}(?=📢)', '', excerpt_clean)
        excerpt_clean = re.sub(r'\s{2,}', ' ', excerpt_clean).strip()

        notices.append({
            "id": m.group("href"),
            "title": title_clean,
            "excerpt": excerpt_clean,
            "platforms": platforms,
            "category": category_label,
            "date": date_iso,
            "is_pinned": False,
            "is_new": is_new,
            "url": "https://blog.nasmedia.co.kr" + m.group("href"),
        })

    for notice in notices[:highlight_top_n]:
        highlighted = fetch_highlighted_excerpt(notice["url"])
        if highlighted:
            notice["excerpt"] = highlighted

    return notices


def extract_toss_faq_notices(raw_json: str):
    """토스애즈 공지사항 API(workspaces/{id}/faq/) 파싱. isNew 개념이 없어서
    최근 NEW_WINDOW_DAYS일 이내 발행된 글만 NEW로 표시한다."""
    data = json.loads(raw_json)
    now_kst = datetime.now(KST)
    notices = []

    for item in data.get("success", {}).get("results", []):
        created_raw = item.get("created_time") or ""
        try:
            pub_dt = datetime.fromisoformat(created_raw).replace(tzinfo=KST)
            date_str = pub_dt.strftime("%Y-%m-%d")
            is_new = (now_kst - pub_dt) <= timedelta(days=NEW_WINDOW_DAYS)
        except ValueError:
            date_str = ""
            is_new = False

        notice_id = item.get("id")
        notices.append({
            "id": notice_id,
            "title": (item.get("title") or "").strip(),
            "category": "공지",
            "date": date_str,
            "is_pinned": bool(item.get("is_pinned", False)),
            "is_new": is_new,
            "url": f"https://tossads.toss.im/notice/{notice_id}",
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
            elif source_type == "nasmedia":
                notices = extract_nasmedia_notices(raw, source.get("category_label", ""), source.get("highlight_top_n", 0))
            elif source_type == "toss_faq":
                notices = extract_toss_faq_notices(raw)
            else:
                notices = extract_gfa_notices(raw)
        except ElementTree.ParseError as e:
            print(f"[에러] {platform} 파싱 실패 (RSS XML이 아닌 것 같아요): {e}")
            continue
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[에러] {platform} 파싱 실패 (예상한 JSON 형식이 아닌 것 같아요): {e}")
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
