"""
Google OAuth2 토큰 발급 스크립트 (헤드리스 서버 지원)

실행: python scripts/get_token.py
결과: credentials.json 필요, token.json 생성, refresh_token 출력

헤드리스 서버에서는 URL을 복사 → 로컬 PC 브라우저에서 열어 인증 → 코드 붙여넣기
"""
import json
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = [
    'https://www.googleapis.com/auth/blogger',
    'https://www.googleapis.com/auth/webmasters',
]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_PATH = os.path.join(BASE_DIR, 'token.json')
CREDENTIALS_PATH = os.path.join(BASE_DIR, 'credentials.json')


def main():
    if not os.path.exists(CREDENTIALS_PATH):
        print("[ERROR] credentials.json 파일이 없습니다!")
        print()
        print("=== credentials.json 만드는 방법 ===")
        print("1. https://console.cloud.google.com/ 접속")
        print("2. 프로젝트 생성 (또는 기존 프로젝트 선택)")
        print("3. 'API 및 서비스' → '라이브러리'에서 아래 API 활성화:")
        print("   - Blogger API v3")
        print("   - Google Search Console API (선택)")
        print("4. 'API 및 서비스' → '사용자 인증 정보' → '+ 사용자 인증 정보 만들기'")
        print("   → 'OAuth 클라이언트 ID'")
        print("5. 애플리케이션 유형: '데스크톱 앱' 선택")
        print("6. 만들기 후 JSON 다운로드")
        print(f"7. 다운로드한 파일을 {CREDENTIALS_PATH} 로 저장")
        print()
        print("※ OAuth 동의 화면이 없으면 먼저 설정해야 합니다:")
        print("   'API 및 서비스' → 'OAuth 동의 화면' → '외부' → 테스트 사용자에 본인 이메일 추가")
        sys.exit(1)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("[OK] 기존 토큰 갱신 완료")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )

            # 헤드리스 서버 지원: 브라우저 없으면 수동 URL 방식 사용
            try:
                creds = flow.run_local_server(
                    port=8090,
                    open_browser=False,
                    authorization_prompt_message=(
                        "\n아래 URL을 브라우저에서 열어 인증하세요:\n"
                    ),
                )
            except Exception:
                # run_local_server 실패 시 콘솔 방식으로 폴백
                print("\n[INFO] 로컬 서버 방식 실패 → 수동 인증 모드로 전환합니다.\n")
                flow.redirect_uri = "urn:ietf:wg:oauth:2.0:oob"
                auth_url, _ = flow.authorization_url(
                    access_type='offline',
                    prompt='consent',
                )
                print("=" * 60)
                print("아래 URL을 브라우저(로컬 PC)에서 열어 인증하세요:")
                print("=" * 60)
                print(f"\n{auth_url}\n")
                print("=" * 60)
                code = input("인증 후 표시되는 코드를 여기에 붙여넣으세요: ").strip()
                flow.fetch_token(code=code)
                creds = flow.credentials

            print("[OK] 새 토큰 발급 완료")

        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())

    token_data = json.loads(creds.to_json())
    refresh_token = token_data.get('refresh_token', '')
    client_id = token_data.get('client_id', '')
    client_secret = token_data.get('client_secret', '')

    print("\n" + "=" * 60)
    print("✅ 토큰 발급 성공!")
    print("=" * 60)

    print(f"\n📌 아래 값들을 .env 파일에 복사하세요:\n")
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")

    print(f"\n📁 token.json 저장 위치: {TOKEN_PATH}")

    print("\n" + "=" * 60)
    print("📌 나머지 .env 값 설정 가이드")
    print("=" * 60)
    print("""
BLOG_MAIN_ID
  → Blogger 대시보드 URL에서 확인:
    https://www.blogger.com/blog/posts/[여기가 BLOG_MAIN_ID]
  → 또는 Blogger API로 조회:
    curl -H "Authorization: Bearer ACCESS_TOKEN" \\
      https://www.googleapis.com/blogger/v3/users/self/blogs

GEMINI_API_KEY
  → https://aistudio.google.com/apikey 에서 발급
  → 무료 티어: 분당 15 요청, 일 1500 요청

GEMINI_MODEL (기본: gemini-2.5-flash)
  → gemini-2.5-flash  : 빠르고 저렴 (추천)
  → gemini-2.5-pro    : 고품질, 비용 높음

TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (선택)
  → @BotFather 에서 봇 생성 → 토큰 복사
  → 봇에게 메시지 전송 후:
    curl https://api.telegram.org/bot<TOKEN>/getUpdates
    → result[0].message.chat.id 가 CHAT_ID

BLOG_SITE_URL (선택, Search Console 자동 색인용)
  → 예: https://yourblog.blogspot.com
""")


if __name__ == '__main__':
    main()
