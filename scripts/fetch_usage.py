#!/usr/bin/env python3
"""Fetch Claude Code usage data by making a minimal API call and reading rate limit headers."""

import json
import math
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error

CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
CACHE_DIR = os.path.expanduser("~/.cache/claude-usage")
CACHE_PATH = os.path.join(CACHE_DIR, "usage.json")
API_URL = "https://api.anthropic.com/v1/messages"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
TOKEN_EXPIRY_BUFFER_MS = 5 * 60 * 1000  # refresh 5 minutes before expiry


def read_credentials():
    """Read OAuth credentials. Returns (token, subscription_type) or (None, None)."""
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None
    oauth = creds.get("claudeAiOauth") or {}
    token = oauth.get("accessToken")
    if not token:
        return None, None
    return token, oauth.get("subscriptionType", "unknown")


def is_token_expired():
    """Check if the OAuth access token is expired or about to expire."""
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return True
    oauth = creds.get("claudeAiOauth") or {}
    expires_at = oauth.get("expiresAt")
    if expires_at is None:
        return False  # no expiry info, assume valid
    now_ms = int(time.time() * 1000)
    return now_ms >= (expires_at - TOKEN_EXPIRY_BUFFER_MS)


def refresh_token():
    """Refresh the OAuth access token using the refresh token. Returns (new_token, subscription_type) or (None, None)."""
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None, None

    oauth = creds.get("claudeAiOauth") or {}
    refresh_tok = oauth.get("refreshToken")
    if not refresh_tok:
        return None, None

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
    except Exception:
        return None, None

    new_access = data.get("access_token")
    if not new_access:
        return None, None

    oauth["accessToken"] = new_access
    if "refresh_token" in data:
        oauth["refreshToken"] = data["refresh_token"]
    if "expires_in" in data:
        oauth["expiresAt"] = int(time.time() * 1000) + data["expires_in"] * 1000

    creds["claudeAiOauth"] = oauth
    try:
        with open(CREDENTIALS_PATH, "w") as f:
            json.dump(creds, f, indent=2)
    except OSError:
        pass

    return new_access, oauth.get("subscriptionType", "unknown")


def is_claude_code_running():
    """Check if a Claude Code CLI process is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "claude"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False


def ensure_valid_token():
    """Return a valid (token, subscription_type), refreshing if needed."""
    token, sub_type = read_credentials()
    if not token:
        return None, None
    if is_token_expired():
        new_token, new_sub = refresh_token()
        if new_token:
            return new_token, new_sub
        # fallthrough: try the current token anyway
    return token, sub_type


def get_auth_status():
    """Get user email and auth info via claude auth status."""
    try:
        result = subprocess.run(
            ["claude", "auth", "status"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError, OSError):
        pass
    return None


def fetch_usage(token):
    payload = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "."}],
    }).encode()

    req = urllib.request.Request(
        API_URL,
        data=payload,
        headers={
            "x-api-key": token,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    resp = urllib.request.urlopen(req, timeout=15)
    headers = resp.headers

    result = {
        "five_hour_percent": None,
        "five_hour_reset": None,
        "weekly_percent": None,
        "weekly_reset": None,
        "status": headers.get("anthropic-ratelimit-unified-status", "unknown"),
        "timestamp": int(time.time()),
        "error": None,
    }

    val = headers.get("anthropic-ratelimit-unified-5h-utilization")
    if val is not None:
        result["five_hour_percent"] = math.ceil(float(val) * 100)
    val = headers.get("anthropic-ratelimit-unified-5h-reset")
    if val is not None:
        result["five_hour_reset"] = val

    val = headers.get("anthropic-ratelimit-unified-7d-utilization")
    if val is not None:
        result["weekly_percent"] = math.ceil(float(val) * 100)
    val = headers.get("anthropic-ratelimit-unified-7d-reset")
    if val is not None:
        result["weekly_reset"] = val

    return result


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def save_cache(data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(data, f)


def is_cache_fresh(cached, ttl_minutes):
    """Return True if the cached data is younger than ttl_minutes."""
    if not cached:
        return False
    ts = cached.get("timestamp")
    if ts is None:
        return False
    return (time.time() - ts) < ttl_minutes * 60


def build_not_logged_in():
    return {
        "error": "not_logged_in",
        "logged_in": False,
        "email": None,
        "subscription_type": None,
        "five_hour_percent": None,
        "weekly_percent": None,
        "five_hour_reset": None,
        "weekly_reset": None,
    }


def main():
    # Parse --ttl argument (default: 5 minutes)
    ttl_minutes = 5
    if "--ttl" in sys.argv:
        idx = sys.argv.index("--ttl")
        if idx + 1 < len(sys.argv):
            try:
                ttl_minutes = max(1, int(sys.argv[idx + 1]))
            except ValueError:
                pass

    if "--status" in sys.argv:
        token, sub_type = read_credentials()
        if not token:
            print(json.dumps(build_not_logged_in()))
            return
        result = {"logged_in": True, "subscription_type": sub_type, "email": None}
        auth = get_auth_status()
        if auth:
            result["email"] = auth.get("email")
            result["subscription_type"] = auth.get("subscriptionType", sub_type)
        cached = load_cache()
        if cached:
            for key in ("five_hour_percent", "weekly_percent", "five_hour_reset", "weekly_reset", "timestamp"):
                result[key] = cached.get(key)
        print(json.dumps(result))
        return

    if "--logout" in sys.argv:
        try:
            os.remove(CACHE_PATH)
        except FileNotFoundError:
            pass
        print(json.dumps({"logged_out": True}))
        return

    if "--cached" in sys.argv:
        token, sub_type = read_credentials()
        logged_in = token is not None
        cached = load_cache()
        if cached:
            cached["logged_in"] = logged_in
            cached["subscription_type"] = sub_type if logged_in else None
            print(json.dumps(cached))
        else:
            result = build_not_logged_in() if not logged_in else {
                "error": "no cached data",
                "logged_in": True,
                "subscription_type": sub_type,
                "email": None,
                "five_hour_percent": None,
                "weekly_percent": None,
            }
            print(json.dumps(result))
        return

    # Default: fetch fresh data, respecting TTL and Claude Code running state
    force = "--force" in sys.argv

    token, sub_type = read_credentials()
    if not token:
        print(json.dumps(build_not_logged_in()))
        return

    cached = load_cache()

    # Serve from cache if still within the TTL window — unless --force is set
    if not force and is_cache_fresh(cached, ttl_minutes):
        if cached:
            cached["logged_in"] = True
            cached["subscription_type"] = sub_type
            if not cached.get("email"):
                auth = get_auth_status()
                if auth:
                    cached["email"] = auth.get("email")
                    cached["subscription_type"] = auth.get("subscriptionType", sub_type)
            print(json.dumps(cached))
            return

    # Cache is stale and Claude Code is not running — refresh token and call API
    token, sub_type = ensure_valid_token()
    if not token:
        print(json.dumps(build_not_logged_in()))
        return

    email = (cached or {}).get("email")
    if not email:
        auth = get_auth_status()
        if auth:
            email = auth.get("email")
            sub_type = auth.get("subscriptionType", sub_type)

    try:
        result = fetch_usage(token)
        result["logged_in"] = True
        result["subscription_type"] = sub_type
        result["email"] = email
        save_cache(result)
        print(json.dumps(result))
    except Exception as e:
        if cached:
            cached["error"] = str(e)
            cached["logged_in"] = True
            print(json.dumps(cached))
        else:
            out = build_not_logged_in()
            out["error"] = str(e)
            out["logged_in"] = True
            out["subscription_type"] = sub_type
            out["email"] = email
            out["timestamp"] = int(time.time())
            print(json.dumps(out))


if __name__ == "__main__":
    main()
