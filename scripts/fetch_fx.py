#!/usr/bin/env python3
"""
ECB 기준환율을 받아 저장소에 정적 파일로 저장한다.

★ 왜 이렇게 하는가 ★
지금은 앱이 Frankfurter API를 직접 호출한다. 이 구조의 문제는 두 가지다.
  1) 외부 서비스가 죽으면 앱의 환율 기능도 죽는다
  2) 사용자 수만큼 외부 API 호출이 발생한다

GitHub Actions가 하루 한 번 받아서 저장소에 커밋해두면,
앱은 다른 설정 파일(rates.json)과 똑같이 raw.githubusercontent에서 읽는다.
  - 런타임 외부 의존 0
  - GitHub CDN이 트래픽을 받아주므로 사용자가 늘어도 문제없다
  - 공급처를 바꿔도 이 스크립트만 고치면 된다 (앱 업데이트 불필요)

⚠️ 한계: 하루 한 번 갱신이다. 실시간 환율이 필요하면 이 방식은 맞지 않다.
   다만 ECB 자체가 영업일 1회 고시라 원래 실시간이 아니다.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

# 앱이 지원하는 통화. Currencies.LIST와 맞춰야 한다.
CURRENCIES = [
    "KRW", "USD", "JPY", "EUR", "CNY", "GBP", "AUD", "CAD", "CHF",
    "HKD", "SGD", "THB", "NZD", "PHP", "IDR", "MYR", "INR", "TRY",
    "MXN", "BRL",
]

SOURCE = "https://api.frankfurter.dev/v1/latest"
OUT_DIR = "fx"
TIMEOUT = 15


def fetch(base):
    """기준 통화 하나에 대한 환율을 받아온다. 실패하면 None."""
    url = "{}?base={}".format(SOURCE, base)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            if r.status != 200:
                print("  {}: HTTP {}".format(base, r.status), file=sys.stderr)
                return None
            return json.loads(r.read().decode())
    except Exception as e:
        print("  {}: 실패 - {}".format(base, e), file=sys.stderr)
        return None


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    ok = 0
    failed = []

    for code in CURRENCIES:
        data = fetch(code)

        # ⚠️ 실패한 통화는 기존 파일을 그대로 둔다.
        #    덮어쓰면 환율이 사라져 앱에서 "불러오지 못했습니다"가 뜬다.
        #    오래된 환율이라도 없는 것보다 낫다.
        if not data or "rates" not in data:
            failed.append(code)
            continue

        # 앱의 CurrencyRepository가 기대하는 형태로 맞춘다.
        # date / base / rates 세 키가 필수다.
        out = {
            "_comment": "GitHub Actions가 자동 생성합니다. 직접 수정하지 마세요.",
            "_source": "European Central Bank via frankfurter.dev",
            "_fetchedAt": now,
            "date": data.get("date", ""),
            "base": code,
            "rates": data["rates"],
        }

        path = os.path.join(OUT_DIR, "{}.json".format(code))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
            f.write("\n")

        print("  {}: {}종 (기준일 {})".format(code, len(data["rates"]), data.get("date")))
        ok += 1

    print("\n성공 {} / 실패 {}".format(ok, len(failed)))
    if failed:
        print("실패 통화: {}".format(", ".join(failed)), file=sys.stderr)

    # ⚠️ 일부 실패는 성공으로 처리한다.
    #    한두 통화 때문에 워크플로가 실패하면 나머지 갱신분도 커밋되지 않는다.
    #    전부 실패했을 때만 오류로 본다.
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
