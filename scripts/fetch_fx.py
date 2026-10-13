#!/usr/bin/env python3
"""
ECB 기준환율을 받아 저장소에 정적 파일로 저장한다.

★ 왜 이렇게 하는가 ★
앱이 외부 API를 직접 호출하면 두 가지 문제가 있다.
  1) 외부 서비스가 죽으면 앱의 환율 기능도 죽는다
  2) 사용자 수만큼 외부 API 호출이 발생한다

Actions가 하루 한 번 받아 저장소에 커밋해두면, 앱은 다른 설정 파일과
똑같이 raw.githubusercontent에서 읽는다. 런타임 외부 의존이 0이 된다.

★ API는 한 번만 호출한다 ★
ECB 환율은 모두 EUR 기준으로 고시된다.
EUR 기준 환율 하나만 받으면 나머지 조합은 나눗셈으로 구할 수 있다.
    rate(A→B) = rateEUR[B] / rateEUR[A]
20개 통화에 20번 호출할 이유가 없다. 호출이 적을수록 차단 위험도 줄어든다.

⚠️ User-Agent를 반드시 지정할 것.
   urllib 기본값(Python-urllib/3.x)은 많은 서비스의 WAF가 봇으로 보고 403을 낸다.
   GitHub Actions의 IP 대역이라 더 쉽게 걸린다.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# 앱이 지원하는 통화. Currencies.LIST와 맞춰야 한다.
CURRENCIES = [
    "KRW", "USD", "JPY", "EUR", "CNY", "GBP", "AUD", "CAD", "CHF",
    "HKD", "SGD", "THB", "NZD", "PHP", "IDR", "MYR", "INR", "TRY",
    "MXN", "BRL",
]

# ⚠️ 기본 UA는 403을 맞는다. 평범한 UA를 쓴다.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dcalc-config/1.0; "
                  "+https://github.com/optisj/dcalc-config)",
    "Accept": "application/json",
}

# 한 곳이 막히면 다음 주소를 시도한다.
# frankfurter.dev와 frankfurter.app은 같은 서비스의 다른 도메인이다.
SOURCES = [
    "https://api.frankfurter.dev/v1/latest",
    "https://api.frankfurter.app/latest",
]

OUT_DIR = "fx"
TIMEOUT = 20


def http_get(url):
    """User-Agent를 붙여 GET. 실패하면 None."""
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status != 200:
                print("  HTTP {} - {}".format(r.status, url), file=sys.stderr)
                return None
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        print("  HTTP {} - {}".format(e.code, url), file=sys.stderr)
        return None
    except Exception as e:
        print("  실패 - {} ({})".format(e, url), file=sys.stderr)
        return None


def fetch_eur_base():
    """
    EUR 기준 환율을 한 번만 받아온다.

    ECB는 모든 환율을 EUR 기준으로 고시하므로 이것 하나면 충분하다.
    반환: (날짜, {통화: EUR 대비 환율}) — EUR 자신은 1.0으로 포함
    """
    symbols = ",".join(c for c in CURRENCIES if c != "EUR")

    for base_url in SOURCES:
        url = "{}?base=EUR&symbols={}".format(base_url, symbols)
        print("조회: {}".format(url))
        data = http_get(url)

        if data and "rates" in data:
            rates = dict(data["rates"])
            rates["EUR"] = 1.0   # 기준 통화 자신
            return data.get("date", ""), rates

        print("  → 다음 주소 시도", file=sys.stderr)

    return None, None


def main():
    date, eur_rates = fetch_eur_base()

    if not eur_rates:
        # ⚠️ 받아오지 못하면 파일을 건드리지 않는다.
        #    덮어쓰면 앱에서 환율이 사라진다. 오래된 값이라도 없는 것보다 낫다.
        print("\n환율을 받아오지 못했습니다. 기존 파일을 유지합니다.", file=sys.stderr)
        return 1

    missing = [c for c in CURRENCIES if c not in eur_rates]
    if missing:
        print("경고: 응답에 없는 통화 - {}".format(", ".join(missing)), file=sys.stderr)

    available = [c for c in CURRENCIES if c in eur_rates]
    print("\n수신: {}종 (기준일 {})".format(len(available), date))

    os.makedirs(OUT_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0

    for base in available:
        # 교차 환율: base 1단위가 target 몇 단위인지
        #   rate(base→target) = rateEUR[target] / rateEUR[base]
        base_rate = eur_rates[base]
        if base_rate <= 0:
            print("  {}: 환율이 0 이하 - 건너뜀".format(base), file=sys.stderr)
            continue

        rates = {}
        for target in available:
            if target == base:
                continue   # 자기 자신은 넣지 않는다 (앱이 1.0으로 처리)
            # 소수점을 과하게 남기면 파일만 커지고 의미가 없다
            rates[target] = round(eur_rates[target] / base_rate, 8)

        out = {
            "_comment": "GitHub Actions가 자동 생성합니다. 직접 수정하지 마세요.",
            "_source": "European Central Bank via frankfurter",
            "_note": "EUR 기준 고시환율에서 교차 계산한 값입니다.",
            "_fetchedAt": now,
            "date": date,
            "base": base,
            "rates": rates,
        }

        path = os.path.join(OUT_DIR, "{}.json".format(base))
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
            f.write("\n")
        written += 1

    print("{}개 파일 생성 완료".format(written))

    # 눈으로 확인하기 좋은 대표 환율 한 줄
    if "USD" in eur_rates and "KRW" in eur_rates:
        usd_krw = eur_rates["KRW"] / eur_rates["USD"]
        print("  참고: 1 USD = {:,.2f} KRW".format(usd_krw))

    return 0 if written > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
