"""
Google OAuth2 토큰 발급 스크립트 (헤드리스 서버 지원)

실행: python scripts/get_token.py
결과: credentials.json 필요, token.json 생성, refresh_token 출력

방식: 인증 URL → 브라우저 열기 → 리다이렉트된 localhost URL 복사 → 붙여넣기
"""
import json
import os
import sys
import socket
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

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


def _get_auth_code_manually(flow):
    """헤드리스 서버용: URL 출력 → 브라우저 인증 → 리다이렉트 URL 붙여넣기"""

    # localhost 리다이렉트 URI 설정
    flow.redirect_uri = "http://localhost:8090"

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
    )

    print()
    print("=" * 70)
    print("  Google OAuth2 인증")
    print("=" * 70)
    print()
    print("1. 아래 URL을 복사해서 로컬 PC 브라우저에서 엽니다:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. Google 계정으로 로그인 → '허용' 클릭")
    print()
    print("3. 브라우저가 'localhost:8090...' 으로 리다이렉트되면서")
    print("   '사이트에 연결할 수 없음' 에러가 나옵니다. 정상입니다!")
    print()
    print("4. 브라우저 주소창의 전체 URL을 복사해서 아래에 붙여넣으세요:")
    print("   (예: http://localhost:8090/?code=4/0Axx...&scope=...)")
    print()
    print("=" * 70)

    redirect_url = input("\n붙여넣기 → ").strip()

    # URL에서 code 파라미터 추출
    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    if 'code' not in params:
        print("\n[ERROR] URL에서 인증 코드를 찾을 수 없습니다.")
        print("복사한 URL에 '?code=' 가 포함되어 있는지 확인하세요.")
        sys.exit(1)

    code = params['code'][0]
    flow.fetch_token(code=code)
    return flow.credentials


def _try_local_server(flow):
    """브라우저가 있는 환경: 로컬 서버로 자동 콜백 수신"""
    try:
        creds = flow.run_local_server(
            port=8090,
            open_browser=False,
            authorization_prompt_message="",
        )

        # run_local_server가 성공하면 URL을 출력해야 하는데
        # open_browser=False면 URL을 자체 출력함
        return creds
    except Exception:
        return None


def main():
    if not os.path.exists(CREDENTIALS_PATH):
        print("[ERROR] credentials.json 파일이 없습니다!")
        print()
        print("=" * 60)
        print("  credentials.json 만드는 방법")
        print("=" * 60)
        print()
        print("1. https://console.cloud.google.com/ 접속")
        print("2. 프로젝트 생성 (또는 기존 프로젝트 선택)")
        print()
        print("3. API 활성화:")
        print("   'API 및 서비스' → '라이브러리'에서:")
        print("   - 'Blogger API v3' 검색 → 활성화")
        print("   - 'Google Search Console API' 검색 → 활성화 (선택)")
        print()
        print("4. OAuth 동의 화면 설정 (처음 한번만):")
        print("   'API 및 서비스' → 'OAuth 동의 화면'")
        print("   → User Type: '외부' 선택 → 만들기")
        print("   → 앱 이름, 이메일 입력 → 저장")
        print("   → '테스트 사용자' 탭 → 본인 Gmail 추가")
        print()
        print("5. OAuth 클라이언트 ID 생성:")
        print("   'API 및 서비스' → '사용자 인증 정보'")
        print("   → '+ 사용자 인증 정보 만들기' → 'OAuth 클라이언트 ID'")
        print("   → 애플리케이션 유형: '데스크톱 앱'")
        print("   → 만들기 → JSON 다운로드")
        print()
        print(f"6. 다운로드한 파일 이름을 'credentials.json'으로 바꿔서")
        print(f"   여기에 저장: {CREDENTIALS_PATH}")
        print()
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

            # 헤드리스 서버: 수동 URL 복사 방식
            creds = _get_auth_code_manually(flow)
            print("\n[OK] 새 토큰 발급 완료!")

        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())

    token_data = json.loads(creds.to_json())
    refresh_token = token_data.get('refresh_token', '')
    client_id = token_data.get('client_id', '')
    client_secret = token_data.get('client_secret', '')

    print()
    print("=" * 60)
    print("  토큰 발급 성공! 아래 값을 .env 에 복사하세요")
    print("=" * 60)
    print()
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
    print()
    print(f"token.json 저장 위치: {TOKEN_PATH}")

    print()
    print("=" * 60)
    print("  나머지 .env 값 설정 가이드")
    print("=" * 60)
    print("""
BLOG_MAIN_ID
  Blogger 대시보드 접속 → 주소창에서 확인:
  https://www.blogger.com/blog/posts/[여기가 BLOG_MAIN_ID]

GEMINI_API_KEY
  https://aistudio.google.com/apikey 에서 발급

GEMINI_MODEL (기본: gemini-2.5-flash)
  gemini-2.5-flash  : 빠르고 저렴 (추천)
  gemini-2.5-pro    : 고품질, 비용 높음

TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (선택)
  @BotFather 에서 봇 생성 → 토큰 복사
  봇에게 아무 메시지 전송 후:
  curl https://api.telegram.org/bot<TOKEN>/getUpdates
  → result[0].message.chat.id 가 CHAT_ID

BLOG_SITE_URL (선택, Search Console 자동 색인용)
  예: https://yourblog.blogspot.com
""")


if __name__ == '__main__':
    main()
