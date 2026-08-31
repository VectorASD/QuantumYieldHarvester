try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google.auth import _helpers as g_helpers
except ImportError:
    print("Please enter:")
    print("  pip install -r requirements.txt")
    exit(1)

from secrets import Storage
from setup_credentials import CREDENTIALS_FILE

from pathlib import Path

TOKEN_FILE = Path("bases") / "gmail_token.asd"
SCOPES = ('https://www.googleapis.com/auth/gmail.readonly',)


def load_credentials(storage: Storage) -> dict:
    client_config = storage.load(CREDENTIALS_FILE, name="Google OAuth credentials")
    if client_config is None:
        raise RuntimeError("OAuth client credentials not found. Run setup_credentials.py first")
    return client_config

def load_token(storage: Storage) -> Credentials | None:
    token = storage.load(TOKEN_FILE, name="Gmail token")
    if token is not None and isinstance(token, Credentials):
        return token
    return

def save_token(storage: Storage, creds: Credentials):
    """Save Gmail token to storage.

    Credentials already contain `__getstate__` and `__setstate__`.
    This also applies to datetime.datetime in the `expiry` field.
    """
    storage.store(creds, None, TOKEN_FILE, name="Gmail token")

def print_alive(creds: Credentials):
    skewed_expiry = creds.expiry - g_helpers.REFRESH_THRESHOLD
    print("Token is still alive for:", skewed_expiry - g_helpers.utcnow())

def get_valid_token(storage: Storage) -> Credentials:
    creds = load_token(storage)
    if creds is not None:
        if creds.valid:
            print_alive(creds)
            return creds
        if creds.expired:
            print("Token is expired")
            if creds.refresh_token:
                try:
                    creds.refresh(Request())
                    save_token(storage, creds)
                    print_alive(creds)
                    return creds
                except Exception as e:
                    print(f"Token refresh failed: {e}")
                    # fall through to full OAuth
    # No valid token, run OAuth flow
    client_config = load_credentials(storage)
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0)
    save_token(storage, creds)
    print_alive(creds)
    return creds


if __name__ == "__main__":
    storage = Storage("credential_keys.asd")
    get_valid_token(storage)
