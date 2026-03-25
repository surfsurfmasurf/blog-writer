# 블로그 자동 수익 엔진 (Blog Auto Revenue Engine)

AI 기반 한국어 블로그 자동화 시스템.
트렌드 수집 → AI 글 작성 → 자동 발행 → 수익 링크 삽입 → 성과 분석까지 전 과정을 자동화합니다.

> **Phase 1 목표:** Google Blogger 블로그 1개로 시작해 검색 자산 축적 + AdSense 승인

---

## 목차

1. [시스템 구조](#시스템-구조)
2. [사전 준비](#사전-준비)
3. [설치 방법](#설치-방법)
4. [API 키 설정](#api-키-설정)
5. [Google OAuth 인증](#google-oauth-인증)
6. [실행하기](#실행하기)
7. [Telegram 명령어](#telegram-명령어)
8. [이미지 모드 선택](#이미지-모드-선택)
9. [콘텐츠 코너 구성](#콘텐츠-코너-구성)
10. [Phase 로드맵](#phase-로드맵)
11. [자주 묻는 질문](#자주-묻는-질문)

---

## 시스템 구조

```
봇 레이어 (Python)          AI 레이어 (Gemini API)
─────────────────           ────────────────────
수집봇                       writer_bot.py
  └─ 트렌드 수집               └─ 글감 → Gemini → 완성 글
  └─ 품질 점수 계산
  └─ 폐기 규칙 적용
          │
          ▼
발행봇 ── 링크봇 ── 이미지봇
  └─ 안전장치        └─ 만평 이미지
  └─ Blogger 발행
  └─ Search Console
          │
          ▼
분석봇 → Telegram 리포트
run.py → 즉시 실행 (수집→작성→발행)
스케줄러 → 자동 시간 관리 (cron / Task Scheduler)
```

### 파일 구조

```
blog-writer/
├── run.py                  ← 즉시 실행 진입점 (수집→작성→발행)
├── bots/
│   ├── collector_bot.py    ← 수집봇 (Google Trends, GitHub, HN, RSS)
│   ├── writer_bot.py       ← 글 작성봇 (Gemini API)
│   ├── publisher_bot.py    ← 발행봇 (Blogger API + 안전장치)
│   ├── linker_bot.py       ← 링크봇 (쿠팡 파트너스)
│   ├── analytics_bot.py    ← 분석봇 (5대 핵심 지표)
│   ├── image_bot.py        ← 이미지봇 (만평 3가지 모드)
│   ├── scheduler.py        ← 스케줄러 + Telegram 봇
│   └── article_parser.py   ← Gemini 출력 파서
├── config/
│   ├── blogs.json          ← 블로그 ID 설정
│   ├── schedule.json       ← 발행 시간표
│   ├── sources.json        ← 수집 소스 목록
│   ├── affiliate_links.json← 어필리에이트 링크 DB
│   ├── quality_rules.json  ← 품질 점수 기준
│   └── safety_keywords.json← 안전장치 키워드
├── data/                   ← 런타임 데이터 (gitignore)
├── scripts/
│   ├── get_token.py        ← Google OAuth 토큰 발급
│   ├── setup.sh            ← Linux/macOS 설치 스크립트
│   └── setup.bat           ← Windows 설치 스크립트
├── environment.yml         ← conda 환경 설정
├── .env.example            ← 환경변수 템플릿
└── requirements.txt        ← pip 패키지 목록
```

---

## 사전 준비

### 필수
- **Python 3.11 이상** — [python.org](https://www.python.org/downloads/)
- **Git** — [git-scm.com](https://git-scm.com/)
- **Conda** (권장) — [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 또는 Anaconda
- **Google 계정** — Blogger 블로그 운영용
- **Gemini API Key** — AI 글 작성용 ([Google AI Studio](https://aistudio.google.com/))
- **Telegram 계정** — 봇 알림 수신용

### 선택
- **쿠팡 파트너스 계정** — 링크 수익화용
- **OpenAI API Key** — 이미지 자동 생성 모드 사용 시

---

## 설치 방법

### 1. 저장소 클론

```bash
git clone https://github.com/sinmb79/blog-writer.git
cd blog-writer
```

### 2. 설치 스크립트 실행

**Linux / macOS (conda 자동 감지):**

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

스크립트가 자동으로 처리하는 것:
- conda 환경 생성 (conda 없으면 venv 폴백)
- 패키지 설치
- `.env` 파일 생성
- `data/`, `logs/` 디렉토리 생성
- cron 등록 (선택)

**Windows:**

```cmd
scripts\setup.bat
```

### 3. 수동 설치 (conda)

```bash
conda env create -f environment.yml
conda activate blog-writer
cp .env.example .env
```

### 4. 수동 설치 (venv)

```bash
python3 -m venv venv
source venv/bin/activate        # Linux / macOS
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
cp .env.example .env
```

---

## API 키 설정

`.env` 파일을 열고 아래 항목을 입력합니다.

```env
# ─── Google (필수) ───────────────────────────────────
GOOGLE_CLIENT_ID=         # Google Cloud Console에서 발급
GOOGLE_CLIENT_SECRET=     # Google Cloud Console에서 발급
GOOGLE_REFRESH_TOKEN=     # scripts/get_token.py 실행 후 입력
BLOG_MAIN_ID=             # Blogger 대시보드 URL에서 확인

# ─── Gemini API (필수, 글 작성용) ────────────────────
GEMINI_API_KEY=           # Google AI Studio에서 발급
GEMINI_MODEL=gemini-2.5-flash  # 또는 gemini-2.0-flash, gemini-2.5-pro

# ─── 쿠팡 파트너스 (선택, 링크 수익화) ────────────────
COUPANG_ACCESS_KEY=
COUPANG_SECRET_KEY=

# ─── Telegram (필수, 알림 수신) ──────────────────────
TELEGRAM_BOT_TOKEN=       # @BotFather에서 발급
TELEGRAM_CHAT_ID=         # @userinfobot에서 확인

# ─── 이미지 모드 ─────────────────────────────────────
IMAGE_MODE=manual          # manual | request | auto

# ─── Search Console (선택) ───────────────────────────
BLOG_SITE_URL=            # 예: https://your-blog.blogspot.com/

# ─── OpenAI (auto 모드만 필요) ───────────────────────
OPENAI_API_KEY=
```

### BLOG_MAIN_ID 확인 방법

Blogger 관리자 페이지(blogger.com)에서 블로그를 선택한 뒤 브라우저 주소창을 확인합니다:

```
https://www.blogger.com/blog/posts/XXXXXXXXXXXXXXXXXX
                                   ↑ 이 숫자가 BLOG_MAIN_ID
```

### Telegram 설정 방법

1. Telegram에서 `@BotFather` 검색 → `/newbot` 명령 → 봇 생성 → **Token** 복사
2. 생성한 봇과 대화 시작 → `@userinfobot`에 메시지 → **Chat ID** 확인

---

## Google OAuth 인증

### 1. Google Cloud Console 설정

1. [console.cloud.google.com](https://console.cloud.google.com/) 접속
2. 새 프로젝트 생성
3. **API 및 서비스 → 라이브러리** 에서 아래 두 API 활성화:
   - `Blogger API v3`
   - `Google Search Console API`
4. **사용자 인증 정보 → OAuth 클라이언트 ID 만들기**
   - 애플리케이션 유형: **데스크톱 앱**
5. `credentials.json` 다운로드 → 프로젝트 루트(`blog-writer/`)에 저장

### 2. 토큰 발급

```bash
conda activate blog-writer   # 또는 source venv/bin/activate
python scripts/get_token.py
```

브라우저가 열리면 Google 계정으로 로그인 → 권한 허용
터미널에 출력된 `REFRESH_TOKEN` 값을 `.env`의 `GOOGLE_REFRESH_TOKEN`에 붙여넣기

---

## 실행하기

### 즉시 실행 (권장 — 실행할 때마다 글 1편 작성 + 발행)

```bash
conda activate blog-writer

# 전체 파이프라인: 수집 → 작성 → 발행
python run.py

# 발행 없이 테스트 (글 작성까지만)
python run.py --dry-run

# 수집만
python run.py --collect

# 작성만 (발행 안 함)
python run.py --write
```

### 스케줄러 시작 (백그라운드 자동 발행)

```bash
conda activate blog-writer
python bots/scheduler.py
```

### 각 봇 단독 테스트

```bash
# 수집봇 테스트 (글감 수집)
python bots/collector_bot.py

# 분석봇 테스트 (일일 리포트)
python bots/analytics_bot.py

# 분석봇 주간 리포트
python bots/analytics_bot.py weekly

# 이미지 프롬프트 배치 전송 (request 모드)
python bots/image_bot.py batch
```

### 자동 시작 설정

**Linux (cron):** `scripts/setup.sh` 실행 시 선택적으로 cron 등록. 수동 등록:

```bash
crontab -e
# 매일 09:00 실행
0 9 * * * source /path/to/conda/etc/profile.d/conda.sh && conda activate blog-writer && cd /path/to/blog-writer && python run.py >> logs/cron.log 2>&1
```

**Windows:** 작업 스케줄러(`taskschd.msc`)에서 **BlogEngine** 작업 확인.

---

## 일일 자동 플로우

| 시간 | 작업 |
|------|------|
| 07:00 | 수집봇 — 트렌드 수집 + 품질 점수 계산 + 폐기 필터링 |
| 08:00 | AI 글 작성 트리거 (Gemini API) |
| 09:00 | 발행봇 — 첫 번째 글 발행 |
| 12:00 | 발행봇 — 두 번째 글 발행 |
| 15:00 | 발행봇 — 세 번째 글 (선택) |
| 22:00 | 분석봇 — 일일 리포트 → Telegram 전송 |
| 매주 일요일 22:30 | 분석봇 — 주간 리포트 |
| 매주 월요일 10:00 | 이미지봇 — 프롬프트 배치 전송 (request 모드) |

---

## Telegram 명령어

### 텍스트 명령 (키보드로 입력)

| 명령 | 설명 |
|------|------|
| `발행 중단` | 자동 발행 일시 중지 |
| `발행 재개` | 자동 발행 재개 |
| `오늘 수집된 글감 보여줘` | 오늘 수집된 글감 목록 |
| `대기 중인 글 보여줘` | 수동 검토 대기 글 목록 |
| `이번 주 리포트` | 주간 리포트 즉시 생성 |
| `이미지 목록` | 이미지 제작 현황 |

### 슬래시 명령

| 명령 | 설명 |
|------|------|
| `/status` | 봇 상태 + 이미지 모드 확인 |
| `/approve [번호]` | 수동 검토 글 승인 후 발행 |
| `/reject [번호]` | 수동 검토 글 거부 |
| `/images` | 이미지 제작 대기/진행/완료 현황 |
| `/imgpick [번호]` | 해당 번호 이미지 프롬프트 받기 |
| `/imgbatch` | 프롬프트 배치 수동 전송 |
| `/imgcancel` | 이미지 대기 상태 취소 |

---

## 이미지 모드 선택

`.env`의 `IMAGE_MODE` 값으로 선택합니다.

### `manual` (기본)
한컷 코너 글 발행 시점에 프롬프트 1개를 Telegram으로 전송.
사용자가 직접 이미지를 생성해 `data/images/` 에 파일 저장.

### `request` (권장)
매주 월요일 10:00 대기 중인 프롬프트 목록을 Telegram으로 일괄 전송.

**사용 흐름:**
1. 봇이 프롬프트 목록 전송 (또는 `/imgbatch` 수동 트리거)
2. `/imgpick 3` — 3번 프롬프트 전체 내용 수신
3. 프롬프트 복사 → Midjourney / DALL-E 웹 / Stable Diffusion 등에 붙여넣기
4. 생성된 이미지를 Telegram으로 전송 (캡션에 `#3` 입력 또는 `/imgpick` 후 바로 전송)
5. 봇이 자동 저장 + 완료 처리

### `auto`
OpenAI DALL-E 3 API를 직접 호출해 자동 생성.
`OPENAI_API_KEY` 필요. 이미지당 $0.04–0.08 비용 발생 (ChatGPT Pro 구독과 별도).

---

## 콘텐츠 코너 구성

| 코너 | 컨셉 | 발행 빈도 |
|------|------|-----------|
| **쉬운 세상** | AI/테크를 누구나 따라할 수 있게 | 주 2–3회 |
| **숨은 보물** | 모르면 손해인 무료 도구 발굴 | 주 2–3회 |
| **바이브 리포트** | 비개발자가 AI로 만든 실제 사례 | 주 1–2회 |
| **팩트체크** | 과대광고/거짓 주장 검증 (수동 승인 필수) | 주 1회 이하 |
| **한 컷** | AI/테크 이슈 만평 | 주 1회 |

### 안전장치 (자동 발행 차단 조건)

아래 조건에 해당하면 자동 발행 대신 Telegram으로 수동 검토 요청:
- 팩트체크 코너 글 전체
- 암호화폐/투자/법률 관련 위험 키워드 감지
- 출처 2개 미만
- 품질 점수 75점 미만

---

## Gemini API 글 작성

글 작성은 Google Gemini API를 사용합니다. 별도의 에이전트 설정 없이 `.env`에 API 키만 설정하면 동작합니다.

### 지원 모델

| 모델 | 특징 | `.env` 설정값 |
|------|------|---------------|
| **Gemini 2.5 Flash** (기본) | 빠르고 저렴 | `gemini-2.5-flash` |
| **Gemini 2.0 Flash** | 안정적 | `gemini-2.0-flash` |
| **Gemini 2.5 Pro** | 최고 품질, 비용 높음 | `gemini-2.5-pro` |

### 글 작성 파이프라인

```
수집봇 (글감) → writer_bot.py (Gemini) → article_parser.py (파싱) → publisher_bot.py (발행)
```

- 페르소나, 코너별 톤, 출력 형식이 `bots/writer_bot.py`에 내장되어 있음
- 커스터마이즈: `writer_bot.py`의 `SYSTEM_PROMPT` 수정

---

## Phase 로드맵

| Phase | 기간 | 목표 | 예상 수익 |
|-------|------|------|----------|
| **1** | Month 1–3 | 블로그 1개, 시스템 검증, AdSense 승인 | 0–5만원/월 |
| **2** | Month 3–5 | 블로그 2개, 쿠팡 수익 집중 | 5–20만원/월 |
| **3** | Month 5–8 | 3–4개 블로그, 어필리에이트 추가 | 10–50만원/월 |
| **4** | Month 8+ | 영문 블로그, 글로벌 확장 | 30–100만원+/월 |

---

## 자주 묻는 질문

**Q. Gemini API 키는 어디서 발급하나요?**
A. [Google AI Studio](https://aistudio.google.com/)에서 무료로 발급받을 수 있습니다. 무료 티어로도 하루 수십 회 요청이 가능합니다.

**Q. 다른 LLM으로 교체할 수 있나요?**
A. `bots/writer_bot.py`의 `generate_article()` 함수만 수정하면 됩니다. OpenAI, Claude, 로컬 LLM 등으로 교체 가능합니다.

**Q. Blogger 외 다른 플랫폼을 사용할 수 있나요?**
A. `publisher_bot.py`의 `publish_to_blogger()` 함수를 교체하면 WordPress, 티스토리 등으로 변경 가능합니다.

**Q. Linux에서 어떻게 설치하나요?**
A. `./scripts/setup.sh` 실행하면 conda(또는 venv)로 환경 설정 + cron 등록까지 자동 처리됩니다.

**Q. 수집봇이 아무것도 가져오지 못해요.**
A. `config/sources.json`의 RSS URL이 유효한지 확인하세요. Google Trends는 간혹 요청 제한이 걸릴 수 있으며, 이 경우 `pytrends` 관련 로그를 확인하세요.

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능합니다.
