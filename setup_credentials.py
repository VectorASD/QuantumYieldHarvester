"""Save Google OAuth client ID JSON securely using secrets.Storage"""

from user_api import User, json_value
from secrets import Storage

from pathlib import Path


CREDENTIALS_FILE = Path("bases") / "credentials.asd"

def is_oauth_client_json(data: json_value) -> bool:
    """Check if data is a valid OAuth client JSON"""
    if not isinstance(data, dict):
        return False
    client_info = data.get("installed") or data.get("web")
    if not isinstance(client_info, dict):
        return False
    required_string_keys = (
        "client_id",
        "project_id",
        "auth_uri",
        "token_uri",
        "auth_provider_x509_cert_url",
        "client_secret",
    )
    for key in required_string_keys:
        if not isinstance(client_info.get(key), str):
            return False
    return True

def check_save():
    storage = Storage("credential_keys.asd")
    print("Check reading of file: ", end='', flush=True)
    obj = storage.load(CREDENTIALS_FILE)
    if obj is None:
        print("FAILED")
    else:
        print("OK")
        print("Check readed content: ", end='', flush=True)
        print("OK" if is_oauth_client_json(obj) else "FAILED")


def main():
    obj = User.get_json("""
Create OAuth client ID: https://console.cloud.google.com/auth/clients/create
Application type: Desktop app

!!! Important: After creating credentials, you must add your email as a test user:
!!! Go to: https://console.cloud.google.com/auth/audience
!!! (Google Auth Platform -> Audience -> Test users -> "+ Add users")
!!! Enter your Gmail address there. Otherwise you will get 403 access_denied when trying to get tokens.
        """.strip(),
        "Select Google OAuth client JSON"
    )
    if obj is None:
        # canceled by user
        return
    if not is_oauth_client_json(obj):
        print("Invalid credentials")
        return

    storage = Storage("credential_keys.asd")
    storage.store(obj, None, CREDENTIALS_FILE)
    check_save()


if __name__ == "__main__":
    main()
  # check_save()
