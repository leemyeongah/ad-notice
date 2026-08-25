"""
매체 상품소개서 PDF 등록 스크립트

구글 드라이브 대신, PDF 파일 자체를 이 저장소(data/pdfs/) 안에 넣어서
사이트에서 로그인 없이 바로 미리보기가 되게 합니다. (대시보드가 구글 드라이브 파일
링크와 이 저장소 안의 상대경로 링크를 둘 다 인라인 미리보기로 처리합니다)

사용법:
    python add_product_pdf.py "매체명" "C:\\경로\\파일.pdf"

    - "매체명"이 manual_input/products_raw.json에 이미 있으면 그 항목의 링크만 바꿔치기
    - 없으면 이름만 채운 새 항목을 추가함 (나머지 정보는 나중에 직접 채우면 됨)

실행 후:
    git add . && git commit -m "매체 상품소개서 PDF 추가: <매체명>" && git push
"""
import json
import re
import shutil
import sys
from pathlib import Path

import manage_products

BASE_DIR = Path(__file__).parent
PDF_DIR = BASE_DIR / "data" / "pdfs"
MANUAL_INPUT_PATH = BASE_DIR / "manual_input" / "products_raw.json"


def slugify(platform: str) -> str:
    """파일명으로 안전하게 쓸 수 있게 정리 (한글은 유지, 경로에 문제되는 문자만 제거)."""
    safe = re.sub(r'[\\/:*?"<>|]', '', platform).strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe[:60] or "media"


def run():
    if len(sys.argv) != 3:
        print('사용법: python add_product_pdf.py "매체명" "PDF 파일 경로"')
        return

    platform = sys.argv[1].strip()
    pdf_path = Path(sys.argv[2])

    if not platform:
        print("[에러] 매체명이 비어있어요.")
        return
    if not pdf_path.exists() or pdf_path.suffix.lower() != ".pdf":
        print(f"[에러] {pdf_path} 를 찾을 수 없거나 PDF 파일이 아니에요.")
        return

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    dest_name = f"{slugify(platform)}.pdf"
    dest_path = PDF_DIR / dest_name
    shutil.copyfile(pdf_path, dest_path)
    rel_link = f"data/pdfs/{dest_name}"

    raw = json.loads(MANUAL_INPUT_PATH.read_text(encoding="utf-8")) if MANUAL_INPUT_PATH.exists() else []

    entry = next((item for item in raw if (item.get("platform") or "").strip() == platform), None)
    if entry:
        entry["link"] = rel_link
        print(f"[안내] 기존 '{platform}' 항목의 링크를 갱신했어요.")
    else:
        raw.append({
            "platform": platform,
            "category": "",
            "summary": "",
            "description": "",
            "features": [],
            "link": rel_link,
        })
        print(f"[안내] '{platform}'이 목록에 없어서 새 항목을 추가했어요. 나머지 정보는 나중에 채워주세요.")

    MANUAL_INPUT_PATH.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"-> {dest_path} 저장됨")
    manage_products.run()
    print("\n마무리로 아래 명령어를 실행해주세요:")
    print(f'  git add . && git commit -m "매체 상품소개서 PDF 추가: {platform}" && git push')


if __name__ == "__main__":
    run()
