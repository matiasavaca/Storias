import os

# Import Celery/settings without production credentials or broker connections.
for key in (
    "SECRET_KEY", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY",
    "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "ANTHROPIC_API_KEY",
    "ENCRYPTION_KEY",
):
    os.environ.setdefault(key, "test-only")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
