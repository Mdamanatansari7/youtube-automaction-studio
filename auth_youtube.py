import sys
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly'
]

ROOT = Path(__file__).resolve().parent
YT_DIR = ROOT / 'data' / 'youtube'
YT_DIR.mkdir(parents=True, exist_ok=True)
SECRETS = YT_DIR / 'client_secrets.json'
TOKEN = YT_DIR / 'token.json'

def run_auth():
    if not SECRETS.exists():
        print(f"Error: {SECRETS} does not exist.")
        sys.exit(1)
        
    print("\n=======================================================")
    print("Starting Google OAuth Authentication for YouTube...")
    print("A browser window will open automatically.")
    print("Select your Google account and click 'Allow' / 'Continue'.")
    print("=======================================================\n")
    
    flow = InstalledAppFlow.from_client_secrets_file(str(SECRETS), scopes=SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=True, prompt='consent')
    
    TOKEN.write_text(creds.to_json(), encoding='utf-8')
    print("\n✅ Successfully authenticated! Saved token to:", TOKEN)
    
    try:
        yt = build('youtube', 'v3', credentials=creds)
        res = yt.channels().list(mine=True, part='snippet,statistics').execute()
        items = res.get('items', [])
        if items:
            title = items[0]['snippet']['title']
            subs = items[0].get('statistics', {}).get('subscriberCount', '0')
            print(f"🎉 Connected Channel: {title} ({subs} subscribers)")
        else:
            print("Connected, but could not retrieve channel profile.")
    except Exception as e:
        print("Channel verification note:", e)

if __name__ == '__main__':
    run_auth()
