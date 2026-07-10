# 📡 적금 레이더 (savings-monitor)

국내 시중은행·인터넷전문은행의 **적금 상품**을 매시간 자동 수집해:

- 🆕 신규 상품이 등록되면 **텔레그램 채널로 알림** (요약·금리·우대조건·링크·시장 내 위치 분석)
- 📊 **GitHub Pages 웹사이트**에서 전체 상품 비교표(정렬·필터·상세보기) 제공

데이터 출처: [금융감독원 금융상품통합비교공시 「금융상품한눈에」](https://finlife.fss.or.kr) 오픈API

## 구조

| 파일 | 역할 |
|---|---|
| `monitor.py` | FSS API 수집 → 신규 감지 → `docs/data.json` 갱신 → 텔레그램 발송 |
| `.github/workflows/monitor.yml` | 매시간(매시 7분) 자동 실행 |
| `docs/index.html` | 비교 대시보드 (GitHub Pages) |
| `docs/data.json` | 최신 상품 데이터 (자동 커밋) |

## 설정 (Repository secrets)

`Settings → Secrets and variables → Actions → New repository secret`

| 이름 | 값 |
|---|---|
| `FSS_AUTH_KEY` | 금감원 오픈API 인증키 |
| `TELEGRAM_BOT_TOKEN` | @BotFather 발급 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 알림 받을 채널 (예: `@mychannel`) |

GitHub Pages: `Settings → Pages → Deploy from a branch → main / docs`

## 신규 감지 방식

상품 식별키는 `금융회사코드|상품코드` 조합. 공시월(dcls_month)은 매달 바뀌므로 비교에 사용하지 않는다.
첫 실행 시 현재 상품 전체를 기준선으로 저장하고, 이후 실행부터 기준선에 없는 상품을 신규로 판정한다.
