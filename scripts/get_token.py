"""
Google OAuth2 Token Setup Script (headless server support)

Usage: python scripts/get_token.py
Requires: credentials.json in project root
Outputs: token.json + prints REFRESH_TOKEN for .env
"""
import json
import os
import sys
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
    """Headless server: print URL -> user opens in browser -> paste redirect URL"""

    flow.redirect_uri = "http://localhost:8090"

    auth_url, _ = flow.authorization_url(
        access_type='offline',
        prompt='consent',
    )

    print()
    print("=" * 70)
    print("  Google OAuth2 Authentication")
    print("=" * 70)
    print()
    print("1. Copy the URL below and open it in your local browser:")
    print()
    print(f"   {auth_url}")
    print()
    print("2. Sign in with your Google account -> Click 'Allow'")
    print()
    print("3. Your browser will redirect to 'localhost:8090...'")
    print("   You'll see a 'This site can't be reached' error. That's normal!")
    print()
    print("4. Copy the FULL URL from the browser address bar and paste it below:")
    print("   (e.g., http://localhost:8090/?code=4/0Axx...&scope=...)")
    print()
    print("=" * 70)

    redirect_url = input("\nPaste here -> ").strip()

    parsed = urlparse(redirect_url)
    params = parse_qs(parsed.query)

    if 'code' not in params:
        print("\n[ERROR] Could not find authorization code in the URL.")
        print("Make sure the URL contains '?code=' parameter.")
        sys.exit(1)

    code = params['code'][0]
    flow.fetch_token(code=code)
    return flow.credentials


def main():
    if not os.path.exists(CREDENTIALS_PATH):
        print("[ERROR] credentials.json not found!")
        print()
        print("=" * 60)
        print("  How to create credentials.json")
        print("=" * 60)
        print()
        print("1. Go to https://console.cloud.google.com/")
        print("2. Create a project (or select existing one)")
        print()
        print("3. Enable APIs:")
        print("   'APIs & Services' -> 'Library':")
        print("   - Search 'Blogger API v3' -> Enable")
        print("   - Search 'Google Search Console API' -> Enable (optional)")
        print()
        print("4. Set up OAuth consent screen (first time only):")
        print("   'APIs & Services' -> 'OAuth consent screen'")
        print("   -> User Type: 'External' -> Create")
        print("   -> Enter app name, email -> Save")
        print("   -> 'Test users' tab -> Add your Gmail address")
        print()
        print("5. Create OAuth client ID:")
        print("   'APIs & Services' -> 'Credentials'")
        print("   -> '+ Create Credentials' -> 'OAuth client ID'")
        print("   -> Application type: 'Desktop app'")
        print("   -> Create -> Download JSON")
        print()
        print(f"6. Rename the downloaded file to 'credentials.json'")
        print(f"   and save it to: {CREDENTIALS_PATH}")
        print()
        sys.exit(1)

    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            print("[OK] Existing token refreshed")
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDENTIALS_PATH, SCOPES
            )
            creds = _get_auth_code_manually(flow)
            print("\n[OK] New token issued!")

        with open(TOKEN_PATH, 'w') as token_file:
            token_file.write(creds.to_json())

    token_data = json.loads(creds.to_json())
    refresh_token = token_data.get('refresh_token', '')
    client_id = token_data.get('client_id', '')
    client_secret = token_data.get('client_secret', '')

    print()
    print("=" * 60)
    print("  Token issued! Copy these values to your .env file:")
    print("=" * 60)
    print()
    print(f"GOOGLE_CLIENT_ID={client_id}")
    print(f"GOOGLE_CLIENT_SECRET={client_secret}")
    print(f"GOOGLE_REFRESH_TOKEN={refresh_token}")
    print()
    print(f"token.json saved to: {TOKEN_PATH}")

    print()
    print("=" * 60)
    print("  Remaining .env values setup guide")
    print("=" * 60)
    print("""
BLOG_MAIN_ID
  Go to Blogger dashboard -> check the URL:
  https://www.blogger.com/blog/posts/[THIS_IS_YOUR_BLOG_ID]

GEMINI_API_KEY
  Get one at https://aistudio.google.com/apikey

GEMINI_MODEL (default: gemini-2.5-flash)
  gemini-2.5-flash  : Fast and affordable (recommended)
  gemini-2.5-pro    : Higher quality, more expensive

TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID (optional)
  Create bot via @BotFather -> copy token
  Send any message to the bot, then:
  curl https://api.telegram.org/bot<TOKEN>/getUpdates
  -> result[0].message.chat.id is your CHAT_ID

BLOG_SITE_URL (optional, for Search Console auto-indexing)
  e.g., https://yourblog.blogspot.com
""")


if __name__ == '__main__':
    main()
