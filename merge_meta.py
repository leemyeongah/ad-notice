"""
메타 for Business 공지사항 - 수동 입력 병합 스크립트

메타는 자동 크롤링 요청을 차단(400/403)하므로 브라우저에서 직접 복사해 넣는 방식을 씁니다.
계정 정보나 쿠키는 어디에도 저장하지 않습니다.

사용법:
    1. https://www.facebook.com/business/news 등 메타 공지 페이지를 열고
       공지 목록을 아래 형식의 JSON으로 작성해 manual_input/meta_raw.json에 저장
    2. python merge_meta.py 실행
    3. git add . && git commit -m "메타 공지 갱신" && git push

meta_raw.json 형식 (배열):
[
  {
    "title": "공지 제목",
    "url": "https://www.facebook.com/business/...",
    "date": "2026-01-15",
    "category": "광고 업데이트",
    "is_new": true
  },
  ...
]
"""
import json
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MANUAL_INPUT_PATH = BASE_DIR / "manual_input" / "meta_raw.json"
NOTICES_PATH = DATA_DIR / "notices.json"

PLATFORM_NAME = "메타 for Business"
NEW_WINDOW_DAYS = 7


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_meta_notices(items: list) -> list:
    """meta_raw.json 배열을 공통 notices 형식으로 변환."""
    now_kst = datetime.now(KST)
    notices = []
    for item in items:
        date_str = (item.get("date") or "").strip()
        is_new = item.get("is_new", False)
        if date_str and not isinstance(is_new, bool):
            try:
                pub_dt = datetime.fromisoformat(date_str).replace(tzinfo=KST)
                is_new = (now_kst - pub_dt) <= timedelta(days=NEW_WINDOW_DAYS)
            except ValueError:
                is_new = False

        url = (item.get("url") or "").strip()
        notices.append({
            "id": url or item.get("title", ""),
            "title": (item.get("title") or "").strip(),
            "category": (item.get("category") or "").strip(),
            "date": date_str,
            "is_pinned": bool(item.get("is_pinned", False)),
            "is_new": bool(is_new),
            "url": url,
        })
    return notices


def run():
    if not MANUAL_INPUT_PATH.exists():
        print(f"[안내] {MANUAL_INPUT_PATH} 파일이 없어요.")
        print("meta_raw.json 형식으로 공지 목록을 작성한 뒤 다시 실행해주세요.")
        print("예시: [{\"title\": \"...\", \"url\": \"...\", \"date\": \"2026-01-15\", \"category\": \"...\", \"is_new\": true}]")
        return

    raw_text = MANUAL_INPUT_PATH.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[에러] JSON 파싱 실패: {e}")
        return

    if not isinstance(raw, list):
        print("[에러] meta_raw.json은 배열([ ... ]) 형식이어야 합니다.")
        return

    meta_notices = parse_meta_notices(raw)
    for n in meta_notices:
        n["platform"] = PLATFORM_NAME

    existing = load_json(NOTICES_PATH, {"notices": []})
    other = [n for n in existing.get("notices", []) if n.get("platform") != PLATFORM_NAME]
    all_notices = other + meta_notices
    all_notices.sort(key=lambda n: n["date"], reverse=True)

    output = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "new_count": sum(1 for n in all_notices if n.get("is_new")),
        "notices": all_notices,
    }
    save_json(NOTICES_PATH, output)

    new_count = sum(1 for n in meta_notices if n["is_new"])
    print(f"[{PLATFORM_NAME}] {len(meta_notices)}건 병합 완료, NEW 배지 {new_count}건")
    print(f"-> {NOTICES_PATH} 갱신됨")


if __name__ == "__main__":
    run()
