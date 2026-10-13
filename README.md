# dcalc-config

'모두의 계산기' 앱의 원격 설정과 정적 데이터를 담는 저장소.

**별도 서버가 없다.** GitHub Actions가 데이터를 만들고, GitHub CDN이 배포한다.

```
rates.json          앱 설정 (요율, 면책 문구, 공지, 광고 빈도)
fx/<통화>.json       환율 (Actions가 매일 자동 생성)
privacy.html        개인정보 처리방침
oss.html            오픈소스 라이선스
```

---

## GitHub Actions가 하는 일

### 1. 환율 갱신 (`update-fx.yml`)

매일 UTC 16:30에 ECB 기준환율을 받아 `fx/` 에 커밋한다.

```
앱 → raw.githubusercontent.com/<계정>/dcalc-config/main/fx/USD.json
```

**왜 이렇게 하나**

| | 앱이 직접 호출 | Actions가 미리 생성 |
|---|---|---|
| 외부 서비스 중단 시 | 기능 정지 | 영향 없음 |
| 사용자 증가 시 | API 호출도 비례 증가 | GitHub CDN이 흡수 |
| 공급처 변경 | 앱 업데이트 필요 | 스크립트만 수정 |

**⚠️ Actions는 서버가 아니다**

요청에 응답할 수 없다. "미리 만들어 정적 파일로 올려두는" 방식만 가능하다.
실시간 응답이 필요하면 Cloudflare Workers나 Cloud Functions가 필요하다.
다만 ECB가 영업일 1회 고시라 이 방식으로 충분하다.

cron은 GitHub 부하에 따라 수 분~수십 분 지연될 수 있다. 정확한 시각이 필요한
작업에는 쓰지 말 것.

### 2. 설정 검증 (`validate-config.yml`)

`rates.json` 이 바뀌면 자동 검증한다. 이 파일은 푸시하는 순간 24시간 내
전 사용자에게 퍼지므로, 사람이 눈으로 보는 것만으로는 사고를 막을 수 없다.

검사 항목:
- JSON 문법
- 앱이 읽는 필수 키 존재 여부
- 요율·최저임금 범위 (오타로 자릿수가 틀리면 잡힌다)
- **`minSupportedVersionCode` 안전장치**

**가장 중요한 건 마지막이다.** 이 값을 실수로 0이 아닌 상태로 두면
모든 사용자가 앱을 쓸 수 없게 된다. 의도한 변경일 때만 통과하도록
커밋 메시지에 표식을 요구한다.

```bash
git commit -m "긴급: 계산 오류 수정 버전 강제 [force-update]"
```

표식이 없으면 워크플로가 실패하고 푸시가 거부된다.

### 3. 페이지 배포 (`deploy-pages.yml`)

`*.html` 이 바뀌면 GitHub Pages로 배포한다.
`CONTACT_EMAIL` 자리표시자가 남아 있으면 배포를 막는다.

**⚠️ 저장소 Settings → Pages → Source 를 "GitHub Actions" 로 바꿔야 한다.**
"Deploy from a branch" 로 두면 이 워크플로가 무시된다.

---

## 설정

### 1. Actions 쓰기 권한

Settings → Actions → General → Workflow permissions
→ **Read and write permissions** 선택

이게 없으면 환율 커밋 단계에서 실패한다.

### 2. Pages

Settings → Pages → Source → **GitHub Actions**

### 3. 앱 연결

`rates.json` 의 환율 엔드포인트를 정적 파일로 바꾼다.

```json
"currency": {
  "endpoint": "https://raw.githubusercontent.com/<계정>/dcalc-config/main/fx/{base}.json",
  "ttlMinutes": 720,
  "defaultBase": "USD"
}
```

`{base}` 자리에 통화 코드가 들어간다. 앱이 두 형태를 모두 지원하므로,
문제가 생기면 Frankfurter 직접 호출로 되돌릴 수 있다. **앱 업데이트 없이.**

```json
"endpoint": "https://api.frankfurter.dev/v1/latest"
```

---

## 로컬에서 테스트

```bash
# 환율 수집
python3 scripts/fetch_fx.py

# 설정 검증
python3 scripts/validate_config.py

# 강제 업데이트 표식 테스트
COMMIT_MESSAGE="[force-update]" python3 scripts/validate_config.py
```

## 첫 실행

Actions 탭 → 환율 갱신 → Run workflow

cron을 기다리지 않고 바로 `fx/` 파일을 만들 수 있다.

---

## 통화를 추가할 때

두 곳을 함께 고쳐야 한다.

1. `scripts/fetch_fx.py` 의 `CURRENCIES`
2. 앱의 `Currencies.LIST`

앱에만 추가하면 해당 통화의 `fx/<코드>.json` 이 없어 조회에 실패한다.
반대로 스크립트에만 추가하면 파일만 생기고 앱에 안 보인다.
