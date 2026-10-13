# dcalc-config

'모두의 계산기' 앱의 원격 설정과 정적 데이터를 담는 저장소.

**별도 서버가 없다.** GitHub Actions가 데이터를 만들고, GitHub CDN이 배포한다.

```
rates.json          앱 설정 (요율, 면책 문구, 공지, 광고 빈도)
fx/<통화>.json       환율     (Actions가 하루 1회 자동 생성)
fuel/latest.json    유가     (Actions가 매시간 자동 생성)
privacy.html        개인정보 처리방침
oss.html            오픈소스 라이선스
```

앱은 이 파일들을 `raw.githubusercontent.com` 에서 읽는다.
설정을 바꾸면 **앱 업데이트 없이** 24시간 내 전 사용자에게 반영된다.

---

## ⚠️ GitHub Actions는 서버가 아니다

요청에 응답할 수 없다. "미리 만들어 정적 파일로 올려두는" 방식만 가능하다.
실시간 응답이 필요하면 Cloudflare Workers나 Cloud Functions가 필요하다.

다만 이 프로젝트의 데이터는 전부 하루~시간 단위로 바뀌므로 이 방식으로 충분하다.

**cron은 보장되지 않는다.** 부하에 따라 수 분~수십 분 지연되고 드물게 건너뛴다.
앱 쪽에 캐시와 폴백이 있어 기능이 죽지는 않는다. 묵은 값이 보일 뿐이다.

---

## 워크플로

| 워크플로 | 주기 | 하는 일 |
|---|---|---|
| 환율 갱신 | 하루 1회 (UTC 16:30) | ECB 환율 → `fx/` |
| 유가 갱신 | 매시간 (매시 정각) | 오피넷 유가 → `fuel/` |
| 설정 검증 | `rates.json` 변경 시 | 문법·범위·안전장치 검사 |
| 페이지 배포 | `*.html` 변경 시 | GitHub Pages |

전부 **값이 실제로 바뀌었을 때만 커밋**한다. 히스토리가 지저분해지지 않는다.

### 1. 환율 갱신 (`update-fx.yml`)

ECB 기준환율을 받아 `fx/<통화>.json` 으로 커밋한다.

```
앱 → raw.githubusercontent.com/optisj/dcalc-config/main/fx/USD.json
```

| | 앱이 직접 호출 | Actions가 미리 생성 |
|---|---|---|
| 외부 서비스 중단 | 기능 정지 | 영향 없음 |
| 사용자 증가 | API 호출도 비례 증가 | GitHub CDN이 흡수 |
| 공급처 변경 | 앱 업데이트 필요 | 스크립트만 수정 |

**API는 한 번만 호출한다.** ECB는 모든 환율을 EUR 기준으로 고시하므로,
EUR 기준 하나만 받으면 나머지는 나눗셈으로 구할 수 있다.

```
rate(A→B) = rateEUR[B] / rateEUR[A]
```

20개 통화에 20번 호출할 이유가 없다. 호출이 적을수록 차단 위험도 줄고,
모든 파일의 기준일이 정확히 일치한다.

**⚠️ User-Agent를 반드시 지정한다.** `urllib` 기본값(`Python-urllib/3.x`)은
많은 서비스의 WAF가 봇으로 보고 403을 낸다. Actions의 IP 대역이라 더 쉽게 걸린다.
실제로 이 문제로 첫 실행이 실패했다.

### 2. 유가 갱신 (`update-fuel.yml`)

오피넷(한국석유공사) 평균 유가를 받아 `fuel/latest.json` 으로 커밋한다.

**★ 여기가 Actions 방식의 이점이 가장 큰 지점이다 ★**

| | 앱이 직접 호출 | Actions가 미리 생성 |
|---|---|---|
| **API 키** | APK에 박혀 누구나 꺼냄 | **Secrets. 노출 안 됨** |
| **평문 통신** | 오피넷은 `http` → cleartext 예외 필요 | 앱은 `https`만 사용 |
| API 호출량 | 사용자 수에 비례 | 하루 24회 고정 |

오피넷 API 주소는 `http://www.opinet.co.kr/api/...` 로 평문이다.
앱에서 직접 호출하려면 `cleartextTrafficPermitted` 예외를 열어야 하는데,
보안 점검에서 지적받는 항목이다. Actions가 받아오면 이 문제가 사라진다.

**API 키 발급**

1. https://www.opinet.co.kr 회원가입
2. 무료 API 이용 신청 (중소기업·개인 개발자 대상)
3. Settings → Secrets and variables → Actions → New repository secret
   - Name: `OPINET_API_KEY`

**⚠️ 키가 없어도 워크플로는 실패하지 않는다.** 조용히 건너뛴다.
발급 전에는 `rates.json` 의 `fuel.priceUrl` 을 빈 문자열로 두면
앱에서 자동 조회가 꺼지고 사용자가 직접 입력한다.

**⚠️ 전국·시도 평균가다.** 개별 주유소 가격이 아니다.
앱 화면에 기준일과 출처를 표기해야 한다.

### 3. 설정 검증 (`validate-config.yml`)

`rates.json` 이 바뀌면 자동 검증한다. 이 파일은 푸시하는 순간 24시간 내
전 사용자에게 퍼지므로, 사람이 눈으로 보는 것만으로는 사고를 막을 수 없다.

- JSON 문법
- 앱이 읽는 필수 키 존재 여부
- 요율·최저임금 범위 (오타로 자릿수가 틀리면 잡힌다)
- **`minSupportedVersionCode` 안전장치**

**마지막이 가장 중요하다.** 이 값을 0이 아닌 상태로 두면 모든 사용자가
앱을 쓸 수 없게 된다. 의도한 변경일 때만 통과하도록 표식을 요구한다.

```bash
git commit -m "긴급: 계산 오류 수정 버전 강제 [force-update]"
```

표식이 없으면 워크플로가 실패한다.

### 4. 페이지 배포 (`deploy-pages.yml`)

`*.html` 이 바뀌면 GitHub Pages로 배포한다.
`CONTACT_EMAIL` 자리표시자가 남아 있으면 배포를 막는다.

---

## 저장소 설정

### Actions 쓰기 권한 (필수)

```
Settings → Actions → General → Workflow permissions
  → Read and write permissions
```

없으면 데이터 수집은 성공해도 **커밋 단계에서 403**으로 실패한다.
가장 흔한 첫 실행 오류다.

### Pages

```
Settings → Pages → Source → GitHub Actions
```

"Deploy from a branch" 로 두면 기본 배포(`pages-build-deployment`)와
이 워크플로가 **둘 다 돌아** 이중 배포가 된다.
그리고 자리표시자 검사 같은 장치가 작동하지 않는다.

---

## 앱 연결

`rates.json` 의 엔드포인트를 정적 파일로 지정한다.

```json
"currency": {
  "endpoint": "https://raw.githubusercontent.com/optisj/dcalc-config/main/fx/{base}.json",
  "ttlMinutes": 720,
  "defaultBase": "USD"
},
"fuel": {
  "priceUrl": "https://raw.githubusercontent.com/optisj/dcalc-config/main/fuel/latest.json",
  "ttlMinutes": 60
}
```

`{base}` 자리에 통화 코드가 들어간다. (USD, KRW, JPY ...)

**⚠️ `app/src/main/assets/rates.json` 도 같은 내용으로 맞춘다.**
번들이 구버전이면 신규 설치 첫 실행에서 옛 주소로 조회한다.

### 되돌리기

문제가 생기면 `rates.json` 만 고치면 된다. **앱 업데이트 불필요.**

```json
"endpoint": "https://api.frankfurter.dev/v1/latest",
"priceUrl": ""
```

앱이 두 형태를 모두 지원하고, `priceUrl` 이 비면 사용자가 직접 입력한다.

---

## 로컬 테스트

```bash
# 환율 수집
python3 scripts/fetch_fx.py

# 유가 수집 (키 필요)
OPINET_API_KEY=발급받은키 python3 scripts/fetch_fuel.py

# 설정 검증
python3 scripts/validate_config.py

# 강제 업데이트 표식 테스트
COMMIT_MESSAGE="[force-update]" python3 scripts/validate_config.py
```

## 수동 실행

```
Actions 탭 → 워크플로 선택 → Run workflow
```

cron을 기다리지 않고 바로 돌릴 수 있다.

---

## 운영 메모

### 푸시 전에 받아온다

Actions가 수시로 커밋하므로 그냥 푸시하면 거부된다.

```bash
git pull --rebase
```

매번 치기 번거로우면 이 저장소 기본값으로 설정한다.

```bash
git config pull.rebase true
```

### 값을 고칠 때는 `updatedAt` 도 함께

앱 화면에 "요율 기준일" 로 노출된다.
안 바꾸면 원격이 반영됐는지 로그로 구분할 수 없다.

### 통화를 추가할 때

세 곳을 함께 고친다.

1. `scripts/fetch_fx.py` 의 `CURRENCIES`
2. 앱의 `Currencies.LIST`
3. Actions 재실행

앱에만 추가하면 해당 통화의 `fx/<코드>.json` 이 없어 조회에 실패한다.
반대로 스크립트에만 추가하면 파일만 생기고 앱에 안 보인다.

### 갱신 캘린더

| 시기 | 할 일 |
|---|---|
| 매년 1월 | `insurance` 요율, `minimumWage` 시행값 |
| 매년 8월 | 다음 해 최저임금 고시 확인 |
| 수시 | `military` (복무기간 개편), `labor` (근로기준법 개정) |

환율·유가는 자동이라 손댈 일이 없다.
