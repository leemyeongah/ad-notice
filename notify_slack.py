"""
Slack 알림 발송 스크립트

crawler.py(오전 9시 실행)가 찾아둔 신규 소식을 data/pending_slack_notification.json에
남겨두면, 이 스크립트(오전 11시 실행)가 그걸 읽어서 Slack으로 보내고 파일을 비운다.
대시보드 갱신과 Slack 발송 시간을 분리하기 위한 용도.

사용법:
    python notify_slack.py
"""
import json

import crawler

PENDING_PATH = crawler.PENDING_SLACK_PATH


def run():
    if not PENDING_PATH.exists():
        print("보낼 소식 없음 (pending 파일 없음)")
        return

    pending = json.loads(PENDING_PATH.read_text(encoding="utf-8"))
    if not pending:
        print("보낼 소식 없음")
        return

    crawler.notify_slack(pending)
    PENDING_PATH.write_text("[]", encoding="utf-8")


if __name__ == "__main__":
    run()
