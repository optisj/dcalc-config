#!/usr/bin/env python3
"""
오피넷(한국석유공사) 평균 유가를 받아 정적 파일로 저장한다.

★ 왜 Actions로 받는가 ★
  1) API 키를 앱에 넣지 않아도 된다.
     앱에 키를 박으면 APK를 뜯어 누구나 꺼낼 수 있다.
     여기서는 GitHub Secrets에 두므로 노출되지 않는다.
  2) 오피넷 API는 http(평문)다.
     앱이 직접 호출하려면 cleartextTrafficPermitted 예외를 열어야 하는데,
     보안 점검에서 지적받는 항목이다. Actions가 받아오면 앱은 https만 쓴다.
  3) 사용자 수만큼 발생하던 API 호출이 하루 24회로 고정된다.

⚠️ 키가 없으면 조용히 건너뛴다.
   키 발급 전에도 워크플로가 실패하지 않아야 다른 작업에 지장이 없다.

API 키 발급: https://www.opinet.co.kr → 회원가입 → 무료 API 이용 신청
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

API_KEY = os.environ.get("OPINET_API_KEY", "").strip()

BASE = "http://www.opinet.co.kr/api"

# ⚠️ urllib 기본 UA(Python-urllib/3.x)는 WAF가 봇으로 보고 차단하는 경우가 많다.
#    GitHub Actions의 IP 대역이라 더 쉽게 걸린다. 평범한 UA를 지정한다.
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; dcalc-config/1.0; "
                  "+https://github.com/optisj/dcalc-config)",
    "Accept": "application/json",
}
OUT_DIR = "fuel"
TIMEOUT = 15

# 오피넷 유종 코드.
# 앱의 FuelType과 맞춰야 한다.
PRODUCTS = {
    "B027": {"id": "gasoline", "name": "휘발유"},
    "D047": {"id": "diesel", "name": "경유"},
    "B034": {"id": "premium", "name": "고급휘발유"},
    "K015": {"id": "lpg", "name": "자동차용 LPG"},
    "C004": {"id": "kerosene", "name": "실내등유"},
}

# 시도 코드 → 이름.
# 오피넷이 SIDONM을 함께 주지만, 표기가 흔들릴 때를 대비해 고정해 둔다.
SIDO = {
    "01": "서울", "02": "경기", "03": "강원", "04": "충북", "05": "충남",
    "06": "전북", "07": "전남", "08": "경북", "09": "경남", "10": "부산",
    "11": "제주", "14": "대구", "15": "인천", "16": "광주", "17": "대전",
    "18": "울산", "19": "세종",
}


def call(path, params=None):
    """오피넷 API 호출. 실패하면 None."""
    query = "code={}&out=json".format(API_KEY)
    if params:
        query += "&" + "&".join("{}={}".format(k, v) for k, v in params.items())
    url = "{}/{}?{}".format(BASE, path, query)

    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            if r.status != 200:
                print("  {}: HTTP {}".format(path, r.status), file=sys.stderr)
                return None
            # 오피넷은 응답에 BOM이 붙는 경우가 있어 utf-8-sig로 읽는다
            return json.loads(r.read().decode("utf-8-sig"))
    except Exception as e:
        print("  {}: 실패 - {}".format(path, e), file=sys.stderr)
        return None


def to_price(raw):
    """'2011.34' → 2011.34. 변환 실패하면 None."""
    try:
        v = float(str(raw).replace(",", ""))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def fetch_national():
    """전국 평균가 (유종별)"""
    data = call("avgAllPrice.do")
    if not data:
        return None, None

    rows = data.get("RESULT", {}).get("OIL", [])
    prices = {}
    trade_date = ""

    for row in rows:
        code = row.get("PRODCD")
        if code not in PRODUCTS:
            continue
        price = to_price(row.get("PRICE"))
        if price is None:
            continue
        prices[PRODUCTS[code]["id"]] = {
            "name": PRODUCTS[code]["name"],
            "price": round(price, 2),
            # 전일 대비 증감. 앱에서 "▲2.1원" 처럼 보여줄 수 있다.
            "diff": to_price(row.get("DIFF")) or 0.0,
        }
        trade_date = row.get("TRADE_DT", trade_date)

    return prices, trade_date


def fetch_by_region():
    """시도별 평균가"""
    data = call("avgSidoPrice.do")
    if not data:
        return {}

    rows = data.get("RESULT", {}).get("OIL", [])
    regions = {}

    for row in rows:
        code = row.get("PRODCD")
        sido = row.get("SIDOCD")
        if code not in PRODUCTS or sido not in SIDO:
            continue
        price = to_price(row.get("PRICE"))
        if price is None:
            continue

        regions.setdefault(sido, {
            "name": SIDO[sido],
            "prices": {},
        })["prices"][PRODUCTS[code]["id"]] = round(price, 2)

    return regions


def main():
    if not API_KEY:
        # ⚠️ 키가 없어도 실패시키지 않는다.
        #    발급 전에도 다른 워크플로가 정상 동작해야 한다.
        print("OPINET_API_KEY 가 없어 건너뜁니다.")
        print("  저장소 Settings → Secrets and variables → Actions 에서 등록하세요.")
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)

    print("전국 평균가 조회")
    national, trade_date = fetch_national()

    # ⚠️ 전국 평균가를 못 받으면 파일을 쓰지 않는다.
    #    덮어쓰면 앱에서 유가가 사라져 기본값으로 떨어진다.
    #    오래된 값이라도 없는 것보다 낫다.
    if not national:
        print("전국 평균가 조회 실패 — 기존 파일을 유지합니다", file=sys.stderr)
        return 1

    for pid, info in national.items():
        print("  {}: {}원 ({:+.2f})".format(info["name"], info["price"], info["diff"]))

    print("\n시도별 평균가 조회")
    regions = fetch_by_region()
    print("  {}개 시도".format(len(regions)))

    out = {
        "_comment": "GitHub Actions가 자동 생성합니다. 직접 수정하지 마세요.",
        "_source": "한국석유공사 오피넷 (opinet.co.kr)",
        "_fetchedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        # 오피넷 기준일 (YYYYMMDD). 조회한 날짜가 아니라 가격이 집계된 날짜다.
        "tradeDate": trade_date,
        "national": national,
        "regions": regions,
    }

    path = os.path.join(OUT_DIR, "latest.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print("\n{} 저장 완료 (기준일 {})".format(path, trade_date))
    return 0


if __name__ == "__main__":
    sys.exit(main())
