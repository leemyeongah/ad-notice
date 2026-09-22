"""
매체 상품소개서 - 구글 시트 자동 동기화 스크립트

구글 시트의 "매체 업데이트" 탭을 "파일 > 공유 > 웹에 게시 > CSV"로 게시해두면,
이 스크립트가 그 CSV를 그대로 읽어서 data/products.json을 시트 내용과 똑같이 맞춘다
(추가한 항목은 새로 생기고, 시트에서 지운 항목은 여기서도 사라짐 - 매주 전체 재구성).

CSV 게시 링크는 코드에 직접 적지 않고 환경변수 PRODUCTS_SHEET_URL로만 받는다.
(이 저장소는 퍼블릭이라, 링크를 코드에 넣으면 그 자체로 공개되기 때문 -
 GitHub Actions에서는 secrets.PRODUCTS_SHEET_URL로 주입한다)

주의:
- CSV는 서식이 빠지기 때문에, 셀에 파일명만 링크로 걸려있는 경우엔 실제 URL을 못 가져온다.
  "자료" 칸에 파일명 대신 실제 URL을 텍스트로 적어두면 그 링크는 그대로 살아남는다.
- 환경변수가 없으면 아무것도 하지 않고 조용히 끝난다 (기존 워크플로우를 깨지 않기 위함).

사용법:
    PRODUCTS_SHEET_URL="https://.../pub?output=csv" python sync_products.py
"""
import csv
import io
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

KST = ZoneInfo("Asia/Seoul")
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PRODUCTS_PATH = DATA_DIR / "products.json"
MANUAL_INPUT_PATH = BASE_DIR / "manual_input" / "products_raw.json"

SHEET_URL = os.environ.get("PRODUCTS_SHEET_URL", "")

HEADER_ALIASES = {
    "매체": "platform",
    "매체 구분": "category",
    "내용": "description",
    "상품소개서 및 관련 자료": "material",
    "이름": "poc_name",
    "이메일": "poc_email",
    "전화번호": "poc_phone",
    "NEST": "nest",
    "업데이트 기준": "updated",
    "비고": "note",
    "기준 수수료율": "fee_rate",
    "참고사항(백피/마크업)": "fee_basis",
}


def fetch_rows(csv_text: str):
    """헤더 행을 찾아서 그 아래부터 데이터로 보고, 열 이름 기준으로 딕셔너리 리스트를 만든다.
    시트에 병합/설명용 상단 줄이 섞여 있어도 "매체" 헤더가 있는 줄을 자동으로 찾는다."""
    reader = list(csv.reader(io.StringIO(csv_text)))
    header_idx = next((i for i, row in enumerate(reader) if "매체" in row and "상품소개서 및 관련 자료" in row), None)
    if header_idx is None:
        return []

    header = reader[header_idx]
    col_keys = [HEADER_ALIASES.get(h.strip(), None) for h in header]

    rows = []
    for raw_row in reader[header_idx + 1:]:
        row = {}
        for key, value in zip(col_keys, raw_row):
            if key:
                row[key] = value.strip() if value else ""
        if row.get("platform"):
            rows.append(row)
    return rows


def build_products(rows):
    products = []
    for row in rows:
        name = row.get("platform", "")
        material = row.get("material", "")
        note = row.get("note", "")
        nest = row.get("nest", "")

        features = []
        if material and not material.startswith("http"):
            features.append(f"자료: {material}")
        if row.get("poc_name"):
            features.append(f"담당: {row['poc_name']}")
        if row.get("poc_email"):
            features.append(f"이메일: {row['poc_email']}")
        if row.get("poc_phone") and row["poc_phone"] != "-":
            features.append(f"전화: {row['poc_phone']}")
        if nest and nest not in ("-", "Naver게시판"):
            features.append(f"사내 자료명: {nest}")
        if row.get("updated"):
            features.append(f"최근 업데이트 기준: {row['updated']}")
        if note and note != "-" and not note.startswith("http"):
            features.append(f"비고: {note}")

        fee_rate = row.get("fee_rate", "")
        if fee_rate and fee_rate not in ("-",):
            try:
                pct = round(float(fee_rate) * 100)
                line = f"수수료율: {pct}%"
            except ValueError:
                line = f"수수료율: {fee_rate}"
            basis = row.get("fee_basis", "")
            if basis and basis != "-":
                line += f" ({basis})"
            if row.get("category"):
                line += f" · 영역: {row['category']}"
            features.append(line)

        link = material if material.startswith("http") else (note if note.startswith("http") else "")

        products.append({
            "platform": name,
            "category": row.get("category", ""),
            "summary": row.get("description", ""),
            "description": row.get("description", ""),
            "features": features,
            "link": link,
            "_material": material,  # 중복 판별용, 저장 직전에 제거
        })

    # 같은 "자료" 파일을 가리키는 항목이 여러 개면(빈 스텁 + 상세 버전 등) 정보가 더 많은 쪽만 남긴다.
    by_material = {}
    no_material = []
    for p in products:
        key = p["_material"]
        if not key:
            no_material.append(p)
            continue
        prev = by_material.get(key)
        if prev is None or len(p["category"]) + len(p["summary"]) > len(prev["category"]) + len(prev["summary"]):
            by_material[key] = p
    deduped = list(by_material.values()) + no_material
    for p in deduped:
        del p["_material"]
    return deduped


def run():
    if not SHEET_URL:
        print("[안내] PRODUCTS_SHEET_URL이 설정되지 않아 상품소개서 동기화를 건너뜁니다.")
        return

    try:
        resp = requests.get(SHEET_URL, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[에러] 상품소개서 시트 요청 실패: {e}")
        return

    rows = fetch_rows(resp.content.decode("utf-8-sig", errors="replace"))
    if not rows:
        print("[에러] 시트에서 헤더('매체', '상품소개서 및 관련 자료')를 찾지 못했습니다.")
        return

    products = build_products(rows)

    prev = {}
    if PRODUCTS_PATH.exists():
        try:
            prev = json.loads(PRODUCTS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    prev_by_name = {p["platform"]: p for p in prev.get("products", [])}

    # CSV로 게시하면 셀에 파일명으로 걸려있는 구글 드라이브 하이퍼링크는 못 가져온다
    # (CSV엔 서식이 안 남음). 그래서 텍스트로 된 URL이 없으면, 이전에 수동으로 복구해둔
    # PDF 미리보기 링크를 그대로 이어받아 매주 자동 동기화 때 미리보기가 다시 깨지지 않게 한다.
    carried_over = 0
    for p in products:
        prev_link = prev_by_name.get(p["platform"], {}).get("link", "")
        if not p["link"] and prev_link:
            p["link"] = prev_link
            carried_over += 1
    if carried_over:
        print(f"[안내] CSV에 없는 미리보기 링크 {carried_over}건은 이전 데이터에서 이어받음")

    # "이번 주 업데이트된 상품소개서"를 대시보드 상단에 보여주기 위해, 실제로 내용이 바뀐 항목만
    # last_changed_at을 오늘로 갱신한다 (그냥 스크립트가 훑고 지나간 것만으로는 안 바꿈 -
    # 예전엔 매주 전부 다 "오늘 업데이트"로 찍혀서 의미가 없었음).
    # 이 기능 도입 전 데이터(_signature가 하나도 없음)와 비교할 때는 기준선이 아예 없으므로,
    # 그 첫 실행에서만 전체를 "변경 없음"으로 두고 기준선만 새로 잡는다. 그 이후로는 신규 매체가
    # 생기거나 내용이 바뀔 때마다 정상적으로 잡힌다.
    is_bootstrap_run = bool(prev_by_name) and not any("_signature" in p for p in prev_by_name.values())
    today = datetime.now(KST).strftime("%Y-%m-%d")
    changed_count = 0
    for p in products:
        signature = json.dumps(
            {"category": p["category"], "summary": p["summary"], "features": p["features"], "link": p["link"]},
            ensure_ascii=False, sort_keys=True,
        )
        prev_entry = prev_by_name.get(p["platform"])
        if is_bootstrap_run:
            p["last_changed_at"] = ""
        elif prev_entry is None or prev_entry.get("_signature") != signature:
            p["last_changed_at"] = today
            changed_count += 1
        else:
            p["last_changed_at"] = prev_entry.get("last_changed_at", "")
        p["_signature"] = signature
        p["updated_at"] = today
    print(f"[안내] 이번 동기화에서 실제로 내용이 바뀐 매체: {changed_count}건")
    products.sort(key=lambda p: p["platform"])

    MANUAL_INPUT_PATH.parent.mkdir(exist_ok=True)
    INTERNAL_ONLY_FIELDS = {"updated_at", "last_changed_at", "_signature"}
    MANUAL_INPUT_PATH.write_text(
        json.dumps(
            [{k: v for k, v in p.items() if k not in INTERNAL_ONLY_FIELDS} for p in products],
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )

    output = {
        "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
        "products": products,
    }
    DATA_DIR.mkdir(exist_ok=True)
    PRODUCTS_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"상품소개서 {len(products)}건 동기화 완료 -> {PRODUCTS_PATH}")


if __name__ == "__main__":
    run()
