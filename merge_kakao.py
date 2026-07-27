"""
카카오모먼트 공지사항 - 수동 붙여넣기 병합 스크립트

카카오모먼트는 로그인이 있어야만 공지 API가 응답하기 때문에 완전 자동화 대신
이 방식을 씁니다: 브라우저 Network 탭에서 Response를 복사해서 파일로 저장 -> 이 스크립트가 병합.
계정 정보나 쿠키는 어디에도 저장하지 않습니다.

사용법:
    1. 카카오비즈니스 라운지 공지사항 페이지에서 F12 -> Network -> Fetch/XHR
    2. list?serviceType=KAKAOMOMENT... 요청 찾아서 Response 탭 내용 전체 복사
    3. manual_input/kakao_raw.json 파일을 열어서 그 내용을 붙여넣고 저장
    4. python merge_kakao.py 실행
    5. git add . && git commit -m "카카오 공지 갱신" && git push
"""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MANUAL_INPUT_PATH = BASE_DIR / "manual_input" / "kakao_raw.json"
SEEN_IDS_PATH = DATA_DIR / "seen_ids.json"
NOTICES_PATH = DATA_DIR / "notices.json"

PLATFORM_NAME = "카카오모먼트"
# 개별 공지 상세 URL 패턴이 아직 확인되지 않아서, 일단 목록 페이지로 연결합니다.
LIST_URL = "https://lounge-board.kakao.com/bulletin/list?serviceType=KAKAOMOMENT"


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_kakao_notices(raw: dict):
    items = raw.get("data", raw).get("list", [])
    notices = []
    for item in items:
        display_at = item.get("displayStartAt") or item.get("createdAt") or ""
        date = display_at[:10] if display_at else ""
        notices.append({
            "id": item["id"],
            "title": item["title"].strip(),
            "category": item.get("category", {}).get("name", ""),
            "date": date,
            "is_pinned": bool(item.get("pin", False)),
            "url": LIST_URL,
        })
    return notices


def run():
    if not MANUAL_INPUT_PATH.exists():
        print(f"[안내] {MANUAL_INPUT_PATH} 파일이 없어요. 먼저 그 파일에 붙여넣기 해주세요.")
        return

    raw_text = MANUAL_INPUT_PATH.read_text(encoding="utf-8")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(f"[에러] JSON 파싱 실패: {e}")
        print("붙여넣은 내용이 올바른 JSON인지 확인해주세요 (중괄호 짝이 맞는지 등).")
        return

    kakao_notices = parse_kakao_notices(raw)

    seen_ids = load_json(SEEN_IDS_PATH, {})
    platform_seen = set(seen_ids.get(PLATFORM_NAME, []))

    for n in kakao_notices:
        n["platform"] = PLATFORM_NAME
        n["is_new"] = n["id"] not in platform_seen

    seen_ids[PLATFORM_NAME] = list({n["id"] for n in kakao_notices} | platform_seen)
    save_json(SEEN_IDS_PATH, seen_ids)

    existing = load_json(NOTICES_PATH, {"notices": []})
    other_platform_notices = [n for n in existing.get("notices", []) if n.get("platform") != PLATFORM_NAME]
    all_notices = other_platform_notices + kakao_notices
    all_notices.sort(key=lambda n: n["date"], reverse=True)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "new_count": sum(1 for n in all_notices if n.get("is_new")),
        "notices": all_notices,
    }
    save_json(NOTICES_PATH, output)

    new_count = sum(1 for n in kakao_notices if n["is_new"])
    print(f"[{PLATFORM_NAME}] {len(kakao_notices)}건 병합 완료, 신규 {new_count}건")
    print(f"-> {NOTICES_PATH} 갱신됨")


if __name__ == "__main__":
    run()