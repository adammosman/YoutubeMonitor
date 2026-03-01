import os
from dotenv import load_dotenv

load_dotenv()

_cloud_secrets_cache = {}

def _load_cloud_secret(key):
    """Load a single secret from Google Secret Manager."""
    if key in _cloud_secrets_cache:
        return _cloud_secrets_cache[key]
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        project_id = os.environ.get("GCP_PROJECT", "youtube-monitor-488819")
        name = f"projects/{project_id}/secrets/{key}/versions/latest"
        response = client.access_secret_version(name=name)
        value = response.payload.data.decode("UTF-8")
        _cloud_secrets_cache[key] = value
        return value
    except Exception:
        return None

def get(key, default=None):
    # First check environment variables (set by Cloud Function config or .env)
    value = os.environ.get(key)
    if value:
        return value
    
    # In cloud mode, try Secret Manager
    if os.environ.get("GCS_BUCKET"):
        # Map config keys to secret names
        secret_map = {
            "GEMINI_API_KEY": "gemini-api-key",
            "GMAIL_ADDRESS": "gmail-address",
            "GMAIL_APP_PASSWORD": "gmail-app-password",
            "REPORT_RECIPIENT": "report-recipient",
        }
        secret_name = secret_map.get(key)
        if secret_name:
            value = _load_cloud_secret(secret_name)
            if value:
                return value
    
    return default
