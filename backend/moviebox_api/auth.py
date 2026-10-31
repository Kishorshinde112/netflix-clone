import json
import os
from .utils import generate_client_token, get_default_client_info, md5_hex

DEFAULT_GUEST_TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1aWQiOjcwNjU5NDg0MTAyMTM4MTYyMzIsInV0cCI6MSwiZXhwIjoxNzkxNzMyMjMzLCJpYXQiOjE3ODM5NTU5MzN9.7iyEzTj4vWAbOF0oXwNnZ0p3Nc1QaO6K9eMiGFyVfGs"

class MovieBoxAuth:
    def __init__(self, token: str = None, user_id: str = None):
        self.token = token or DEFAULT_GUEST_TOKEN
        self.user_id = user_id or "7065948410213816232"
        self.is_logged_in = True
        self.is_guest_mode = True
        self.client_info = get_default_client_info()
        self.user_info = None
        # REMOVED: self.load_session() - We no longer use a global file for multiple sessions

    def login_guest(self):
        """Perform guest login (Reset back to anonymous state)."""
        self.token = DEFAULT_GUEST_TOKEN
        self.user_id = "7065948410213816232"
        self.is_logged_in = True
        self.is_guest_mode = True
        self.user_info = None

    def update_session(self, token: str, user_id: str = None, user_info: dict = None):
        """Updates the session with a new bearer token and user metadata."""
        self.token = token
        if user_id:
            self.user_id = user_id
        if user_info:
            self.user_info = user_info
        self.is_logged_in = True

    def save_session(self):
        """No-op: Sessions are now managed in memory by the server per-user session ID."""
        pass

    def load_session(self):
        """No-op: Sessions are now managed in memory by the server per-user session ID."""
        pass

    def get_auth_headers(self) -> dict:
        """Returns the current auth headers based on state (Guest vs Authenticated)."""
        headers = {}
        if self.is_logged_in and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
            headers["X-Client-Status"] = "0"
        else:
            headers["X-Client-Token"] = generate_client_token()
            headers["X-Client-Status"] = "1"
        
        headers["X-Client-Info"] = json.dumps(self.client_info, separators=(',', ':'))
        return headers
