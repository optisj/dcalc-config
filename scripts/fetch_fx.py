#!/usr/bin/env python3
"""
ECB 기준환율을 받아 저장소에 정적 파일로 저장한다.
 
★ 왜 이렇게 하는가 ★
앱이 외부 API를 직접 호출하면 두 가지 문제가 있다.
  1) 외부 서비스가 죽으면 앱의 환율 기능도 죽는다
  2) 사용자 수만큼 외부 API 호출이 발생한다
 
Actions가 하루 한 번 받아 저장소에 커밋해두면, 앱은 다른 설정 파일과
똑같이 raw.githubusercontent에서 읽는다. 런타임 외부 의존이 0이 된다.
 
★ API는 소스당 한 번만 호출한다 ★
모든 환율을 EUR 기준으로 받는다.
EUR 기준 환율만 있으면 나머지 조합은 나눗셈으로 구할 수 있다.
    rate(A→B) = rateEUR[B] / rateEUR[A]
 
★ ECB에 없는 통화(TWD, VND 등) ★
ECB는 약 30종만 고시한다. 대만달러·베트남동은 없다.
그래서 2단계로 받는다.
  1차) ECB(frankfurter): 고시하는 통화는 공신력 있는 ECB 값을 쓴다
  2차) 보조 소스: 1차에서 빠진 통화만 채운다 (EUR 기준으로 요청)
1차가 통째로 실패하면 2차가 전부 채운다. 둘 다 실패해야 기존 파일을 유지한다.
 
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
from email.utils import parsedate_to_datetime
 
# 앱이 지원하는 통화. Currencies.LIST와 맞춰야 한다.
CURRENCIES = [
    "KRW", "USD", "JPY", "EUR", "CNY", "GBP", "AUD", "CAD", "CHF",
    "HKD", "SGD", "THB", "NZD", "PHP", "IDR", "MYR", "INR", "TRY",
    "MXN", "BRL",
    "TWD", "VND",   # ECB 미고시 → 보조 소스에서 채움
]
 
# ⚠️ 기본 UA는 403을 맞는다. 평범한 UA를 쓴다.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dcalc-config/1.0; "
                  "+https://github.com/optisj/dcalc-config)",
    "Accept": "application/json",
}
 
# 1차: ECB. 한 곳이 막히면 다음 주소를 시도한다.
# frankfurter.dev와 frankfurter.app은 같은 서비스의 다른 도메인이다.
ECB_SOURCES = [
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
 
 
def clean_rates(raw):
    """대문자 키로 맞추고, 숫자가 아니거나 0 이하인 값은 버린다."""
    out = {}
    for k, v in (raw or {}).items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[k.upper()] = float(v)
    return out
 
 
# ── 보조 소스 파서: 응답 → (날짜, {통화: EUR 대비 환율}) 또는 None ──
 
def parse_fawaz(data):
    # {"date": "2026-10-26", "eur": {"twd": 35.1, "vnd": 28000, ...}}  ← 키가 소문자
    if not data or "eur" not in data:
        return None
    return data.get("date", ""), clean_rates(data["eur"])
 
 
def parse_er_api(data):
    # {"result": "success", "time_last_update_utc": "Sun, 26 Oct 2026 00:02:31 +0000",
    #  "rates": {"TWD": 35.1, ...}}
    if not data or data.get("result") != "success" or "rates" not in data:
        return None
    date = ""
    try:
        date = parsedate_to_datetime(data["time_last_update_utc"]).date().isoformat()
    except Exception:
        pass
    return date, clean_rates(data["rates"])
 
 
# 2차: 보조 소스. 모두 EUR 기준으로 요청한다. 위에서부터 순서대로 시도.
#   (이름, URL, 파서)
FALLBACK_SOURCES = [
    ("fawazahmed0/currency-api",
     "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/eur.json",
     parse_fawaz),
    ("fawazahmed0/currency-api (mirror)",
     "https://latest.currency-api.pages.dev/v1/currencies/eur.json",
     parse_fawaz),
    # ⚠️ 무료 이용 조건: 앱/서비스에 "Rates By Exchange Rate API" 출처 표기 필요
    ("ExchangeRate-API (open access)",
     "https://open.er-api.com/v6/latest/EUR",
     parse_er_api),
]
 
 
def fetch_ecb():
    """
    1차: ECB 기준환율 (EUR 기준).
    반환: (날짜, {통화: EUR 대비 환율}) — EUR 자신은 1.0으로 포함. 실패 시 (None, None)
    """
    # ECB에 없는 통화를 symbols에 넣으면 frankfurter가 에러를 낼 수 있어서
    # symbols 없이 전체를 받은 뒤 필요한 것만 고른다. 응답 크기 차이는 미미하다.
    for base_url in ECB_SOURCES:
        url = "{}?base=EUR".format(base_url)
        print("조회(ECB): {}".format(url))
        data = http_get(url)
 
        if data and "rates" in data:
            rates = clean_rates(data["rates"])
            rates["EUR"] = 1.0   # 기준 통화 자신
            picked = {c: rates[c] for c in CURRENCIES if c in rates}
            return data.get("date", ""), picked
 
        print("  → 다음 주소 시도", file=sys.stderr)
 
    return None, None
 
 
def fetch_fallback(needed):
    """
    2차: needed에 있는 통화만 보조 소스에서 채운다.
    한 소스에서 일부만 채워지면 남은 통화는 다음 소스로 넘어간다.
    반환: ({통화: EUR 대비 환율}, [{"name", "date", "currencies"}])
    """
    remaining = set(needed)
    filled = {}
    used = []
 
    for name, url, parser in FALLBACK_SOURCES:
        if not remaining:
            break
        print("조회(보조): {}".format(url))
        parsed = parser(http_get(url))
        if not parsed:
            print("  → 다음 소스 시도", file=sys.stderr)
            continue
 
        date, rates = parsed
        rates["EUR"] = 1.0
        got = sorted(c for c in remaining if c in rates)
        if not got:
            continue
 
        for c in got:
            filled[c] = rates[c]
        remaining -= set(got)
        used.append({"name": name, "date": date, "currencies": got})
        print("  채움: {}".format(", ".join(got)))
 
    return filled, used
 
 
def main():
    date, eur_rates = fetch_ecb()
    sources = []
 
    if eur_rates:
        sources.append({
            "name": "European Central Bank via frankfurter",
            "date": date,
            "currencies": sorted(eur_rates),
        })
    else:
        print("ECB 조회 실패 - 보조 소스로 전체를 채웁니다.", file=sys.stderr)
        eur_rates = {}
 
    # ECB에서 빠진 통화만 보조 소스로 채운다
    need = [c for c in CURRENCIES if c not in eur_rates]
    if need:
        print("\nECB에 없는 통화: {}".format(", ".join(need)))
        filled, used = fetch_fallback(need)
        eur_rates.update(filled)
        sources.extend(used)
        if not date and used:
            date = used[0]["date"]
 
    if len(eur_rates) < 2:
        # ⚠️ 받아오지 못하면 파일을 건드리지 않는다.
        #    덮어쓰면 앱에서 환율이 사라진다. 오래된 값이라도 없는 것보다 낫다.
        print("\n환율을 받아오지 못했습니다. 기존 파일을 유지합니다.", file=sys.stderr)
        return 1
 
    missing = [c for c in CURRENCIES if c not in eur_rates]
    if missing:
        print("경고: 어느 소스에도 없는 통화 - {}".format(", ".join(missing)), file=sys.stderr)
 
    available = [c for c in CURRENCIES if c in eur_rates]
    print("\n수신: {}종 (기준일 {})".format(len(available), date))
 
    os.makedirs(OUT_DIR, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
 
    for base in available:
        # 교차 환율: base 1단위가 target 몇 단위인지
        #   rate(base→target) = rateEUR[target] / rateEUR[base]
        base_rate = eur_rates[base]
 
        rates = {}
        for target in available:
            if target == base:
                continue   # 자기 자신은 넣지 않는다 (앱이 1.0으로 처리)
            # ⚠️ round(x, 8)은 VND→USD(약 0.00004)처럼 작은 값의 정밀도를 깎는다.
            #    유효숫자 10자리로 저장한다.
            rates[target] = float("{:.10g}".format(eur_rates[target] / base_rate))
 
        out = {
            "_comment": "GitHub Actions가 자동 생성합니다. 직접 수정하지 마세요.",
            "_sources": sources,
            "_note": "EUR 기준 환율에서 교차 계산한 값입니다. "
                     "ECB 미고시 통화는 보조 소스 값이라 기준일이 다를 수 있습니다.",
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
 
    # 눈으로 확인하기 좋은 대표 환율
    for a, b in (("USD", "KRW"), ("TWD", "KRW"), ("VND", "KRW")):
        if a in eur_rates and b in eur_rates:
            print("  참고: 1 {} = {:,.4f} {}".format(a, eur_rates[b] / eur_rates[a], b))
 
    return 0 if written > 0 else 1
 
 
if __name__ == "__main__":
    sys.exit(main())
 
