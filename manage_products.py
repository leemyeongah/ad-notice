"""
매체 상품소개서 - 수동 입력 관리 스크립트

크롤링 대상이 아니라 직접 정리해서 넣는 정보라서, 다른 매체처럼 자동 수집하지 않고
이 스크립트로 manual_input/products_raw.json 내용을 data/products.json에 반영합니다.
같은 platform 이름으로 다시 실행하면 그 매체 항목만 덮어씁니다(upsert).

사용법:
    1. manual_input/products_raw.json 을 아래 형식으로 작성
    2. python manage_products.py 실행
    3. git add . && git commit -m "매체 상품소개서 갱신" && git push

products_raw.json 형식 (배열):
[
  {
    "platform": "네이버",
    "category": "포털/커머스",
    "summary": "한 줄 요약",
    "description": "상세 설명 (여러 줄 가능)",
    "features": ["특징 1", "특징 2"],
    "link": "https://..."
  },
  ...
]
"""
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
MANUAL_INPUT_PATH = BASE_DIR / "manual_input" / "products_raw.json"
PRODUCTS_PATH = DATA_DIR / "products.json"


def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path: Path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run():
    if not MANUAL_INPUT_PATH.exists():
        print(f"[안내] {MANUAL_INPUT_PATH} 파일이 없어요.")
        print("products_raw.json 형식으로 매체별 소개 정보를 작성한 뒤 다시 실행해주세요.")
        return

    try:
        raw = json.loads(MANUAL_INPUT_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"[에러] JSON 파싱 실패: {e}")
        return

    if not isinstance(raw, list):
        print("[에러] products_raw.json은 배열([ ... ]) 형식이어야 합니다.")
        return

    existing = load_json(PRODUCTS_PATH, {"products": []})
    by_platform = {p["platform"]: p for p in existing.get("products", [])}

    today = datetime.now(KST).strftime("%Y-%m-%d")
    updated = []
    for item in raw:
        platform = (item.get("platform") or "").strip()
        if not platform:
            continue
        by_platform[platform] = {
            "platform": platform,
            "category": (item.get("category") or "").strip(),
            "summary": (item.get("summary") or "").strip(),
            "description": (item.get("description") or "").strip(),
            "features": item.get("features") or [],
            "link": (item.get("link") or "").strip(),
            "updated_at": today,
        }
        updated.append(platform)

    products = sorted(by_platform.values(), key=lambda p: p["platform"])
    output = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "products": products,
    }
    save_json(PRODUCTS_PATH, output)

    print(f"{len(updated)}건 반영 완료: {', '.join(updated)}")
    print(f"-> {PRODUCTS_PATH} 갱신됨 (전체 {len(products)}개 매체)")


if __name__ == "__main__":
    run()
