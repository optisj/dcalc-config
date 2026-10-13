#!/usr/bin/env python3
"""
rates.json 검증.

★ 왜 필요한가 ★
이 파일은 푸시하는 순간 24시간 내 전 사용자에게 퍼진다.
실수 하나가 전체 사용자에게 영향을 주므로, 사람이 눈으로 확인하는 것만으로는 부족하다.

검사 항목:
  1) JSON 문법
  2) 앱이 읽는 필수 키 존재 여부
  3) 값의 타입과 범위
  4) 위험한 설정 (전 사용자를 차단할 수 있는 값)

⚠️ 가장 중요한 건 4번이다.
   minSupportedVersionCode를 실수로 큰 값으로 두면 모든 사용자가 앱을 못 쓴다.
   의도적인 경우에만 통과시키기 위해 커밋 메시지에 표식을 요구한다.
"""

import json
import os
import re
import sys

CONFIG = "rates.json"

errors = []
warnings = []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def check_type(data, path, expected, label):
    """중첩 키를 따라가며 타입을 검사한다. path 예: 'insurance.pension'"""
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            err("필수 키 없음: {}".format(path))
            return None
        node = node[part]
    if not isinstance(node, expected):
        err("{} 타입 오류: {} 이어야 하는데 {} ({})".format(
            path, label, type(node).__name__, node))
        return None
    return node


def main():
    if not os.path.exists(CONFIG):
        print("{} 를 찾을 수 없습니다".format(CONFIG), file=sys.stderr)
        return 1

    # ---- 1) JSON 문법 ----
    try:
        with open(CONFIG, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print("JSON 문법 오류: {}행 {}열 - {}".format(e.lineno, e.colno, e.msg),
              file=sys.stderr)
        return 1

    # ---- 2) 필수 구조 ----
    check_type(data, "version", int, "정수")
    updated = check_type(data, "updatedAt", str, "문자열")
    if updated and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated):
        err("updatedAt 형식 오류: YYYY-MM-DD 여야 합니다 ({})".format(updated))

    # ---- 3) 요율 범위 ----
    # 퍼센트 값이 터무니없으면 계산 결과가 통째로 틀어진다
    for path, lo, hi in [
        ("insurance.pension", 0, 20),
        ("insurance.health", 0, 20),
        ("insurance.longTermCare", 0, 50),
        ("insurance.employment", 0, 20),
        ("savings.taxNormal", 0, 50),
        ("savings.taxPreferred", 0, 50),
        ("loan.prepaymentFeeRate", 0, 10),
    ]:
        v = check_type(data, path, (int, float), "숫자")
        if v is not None and not (lo <= v <= hi):
            err("{} 범위 이상: {} (정상 범위 {}~{})".format(path, v, lo, hi))

    wage = check_type(data, "minimumWage.hourly", int, "정수")
    if wage is not None and not (5000 <= wage <= 30000):
        err("최저시급 범위 이상: {} (5,000~30,000 사이여야 합니다)".format(wage))

    # ---- 4) 광고 설정 ----
    ad_max = check_type(data, "ads.showAdRandomMaxCount", int, "정수")
    if ad_max is not None:
        if ad_max < 0:
            err("ads.showAdRandomMaxCount 는 0 이상이어야 합니다: {}".format(ad_max))
        elif ad_max == 1:
            warn("ads.showAdRandomMaxCount=1 은 광고가 꺼진 상태입니다")
        elif 2 <= ad_max <= 4:
            warn("ads.showAdRandomMaxCount={} → 노출 확률 {:.0f}%. "
                 "계산기 앱에는 과도할 수 있습니다".format(ad_max, 100 / ad_max))

    # ---- 5) ★ 위험 설정: 전 사용자 차단 ----
    min_ver = check_type(data, "app.minSupportedVersionCode", int, "정수")
    if min_ver is not None and min_ver != 0:
        # 커밋 메시지에 표식이 있어야 통과시킨다.
        # 실수로 값을 남겨두는 사고를 막는 장치다.
        msg = os.environ.get("COMMIT_MESSAGE", "")
        if "[force-update]" in msg:
            warn("강제 업데이트 활성화: minSupportedVersionCode={} "
                 "(커밋 표식 확인됨)".format(min_ver))
        else:
            err(
                "minSupportedVersionCode 가 0이 아닙니다: {}\n"
                "    이 값 미만 버전의 사용자는 앱을 쓸 수 없게 됩니다.\n"
                "    의도한 변경이면 커밋 메시지에 [force-update] 를 포함하세요.\n"
                "    평상시에는 반드시 0을 유지해야 합니다.".format(min_ver)
            )

    # ---- 6) 공지 ----
    notice = data.get("app", {}).get("notice", {})
    if notice.get("enabled") and not notice.get("message", "").strip():
        err("notice.enabled=true 인데 message 가 비어 있습니다")

    # ---- 7) 면책 문구 ----
    # 비어 있으면 앱에서 안내가 사라져 심사에서 문제가 될 수 있다
    for key in ["health", "legal", "lunar", "military", "insurance"]:
        if not data.get("disclaimers", {}).get(key, "").strip():
            warn("disclaimers.{} 가 비어 있습니다".format(key))

    # ---- 8) 군 복무 정보 ----
    for b in data.get("military", []):
        if not (1 <= b.get("months", 0) <= 48):
            err("복무기간 이상: {} {}개월".format(b.get("name"), b.get("months")))

    # ---- 결과 ----
    for w in warnings:
        print("경고: {}".format(w))
    for e in errors:
        print("오류: {}".format(e), file=sys.stderr)

    if errors:
        print("\n검증 실패 ({}건)".format(len(errors)), file=sys.stderr)
        return 1

    print("\n검증 통과 (경고 {}건)".format(len(warnings)))
    print("  version={}  updatedAt={}".format(data.get("version"), data.get("updatedAt")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
