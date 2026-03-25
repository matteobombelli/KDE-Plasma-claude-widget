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
DEBUG_LOG_PATH = os.path.join(CACHE_DIR, "debug.log")
API_URL = "https://api.anthropic.com/v1/messages"
TOKEN_URL = "https://console.anthropic.com/v1/oauth/token"
TOKEN_EXPIRY_BUFFER_MS = 5 * 60 * 1000  
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

_debug_enabled = False
_claude_version_cache = None


def _get_claude_version():
    global _claude_version_cache
    if _claude_version_cache:
        return _claude_version_cache
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        ver = result.stdout.strip().split()[0]
        _claude_version_cache = ver
        return ver
    except Exception:
        return "unknown"


def debug_log(msg):
    if not _debug_enabled:
        return
    os.makedirs(CACHE_DIR, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(DEBUG_LOG_PATH, "a") as f:
        f.write(f"[{ts}] {msg}\n")


def read_credentials():
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
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return True
    oauth = creds.get("claudeAiOauth") or {}
    expires_at = oauth.get("expiresAt")
    if expires_at is None:
        return False
    now_ms = int(time.time() * 1000)
    return now_ms >= (expires_at - TOKEN_EXPIRY_BUFFER_MS)


def refresh_token():
    try:
        with open(CREDENTIALS_PATH) as f:
            creds = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        return None, None, f"credentials read error: {e}"

    oauth = creds.get("claudeAiOauth") or {}
    refresh_tok = oauth.get("refreshToken")
    if not refresh_tok:
        return None, None, "no refresh token in credentials"

    payload = json.dumps({
        "grant_type": "refresh_token",
        "refresh_token": refresh_tok,
        "client_id": OAUTH_CLIENT_ID,
    }).encode()

    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "content-type": "application/json",
            "user-agent": f"claude-code/{_get_claude_version()}",
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode())
    except Exception as e:
        return None, None, str(e)

    new_access = data.get("access_token")
    if not new_access:
        return None, None, "missing access_token"

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

    return new_access, oauth.get("subscriptionType", "unknown"), None


def is_claude_code_running():
    try:
        result = subprocess.run(["pgrep", "-x", "claude"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def ensure_valid_token(force_refresh=False):
    token, sub_type = read_credentials()
    if not token:
        return None, None, "no credentials found"
    if force_refresh or is_token_expired():
        new_token, new_sub, err = refresh_token()
        if new_token:
            return new_token, new_sub, None
        return token, sub_type, err
    return token, sub_type, None


def get_auth_status():
    try:
        result = subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return json.loads(result.stdout)
    except Exception:
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
            "content-type": "application/json"
        },
        method="POST",
    )

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        headers = resp.headers
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode('utf-8', errors='ignore')
        except Exception:
            pass

        if e.code == 429:
            requests_remaining = e.headers.get("anthropic-ratelimit-requests-remaining")
            
            # If requests_remaining is "0", it's standard API spamming.
            # Otherwise, the 429 is your Pro Message Quota hitting its cap.
            is_spam = (requests_remaining == "0")
            
            if not is_spam:
                reset_val = e.headers.get("anthropic-ratelimit-unified-5h-reset")
                return {
                    "five_hour_percent": 100,
                    "five_hour_reset": reset_val if reset_val else "5h",
                    "weekly_percent": None,
                    "weekly_reset": None,
                    "status": "limit_reached",
                    "timestamp": int(time.time()),
                    "error": None,
                }
        
        e.error_body = error_body
        raise e

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
        result["five_hour_percent"] = min(math.ceil(float(val) * 100) + 1, 100)
    val = headers.get("anthropic-ratelimit-unified-5h-reset")
    if val is not None:
        result["five_hour_reset"] = val

    val = headers.get("anthropic-ratelimit-unified-7d-utilization")
    if val is not None:
        result["weekly_percent"] = min(math.ceil(float(val) * 100) + 1, 100)
    val = headers.get("anthropic-ratelimit-unified-7d-reset")
    if val is not None:
        result["weekly_reset"] = val

    return result


def load_cache():
    try:
        with open(CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_cache(data):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_PATH, "w") as f:
        json.dump(data, f)


def is_cache_fresh(cached, ttl_minutes):
    if not cached: return False
    ts = cached.get("timestamp")
    return ts and (time.time() - ts) < ttl_minutes * 60


def cache_age_seconds(cached):
    if not cached: return None
    ts = cached.get("timestamp")
    return int(time.time() - ts) if ts else None


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
    global _debug_enabled
    _debug_enabled = "--debug" in sys.argv

    ttl_minutes = 5
    if "--ttl" in sys.argv:
        idx = sys.argv.index("--ttl")
        if idx + 1 < len(sys.argv):
            try: ttl_minutes = max(1, int(sys.argv[idx + 1]))
            except ValueError: pass

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

    force = "--force" in sys.argv
    token, sub_type = read_credentials()
    if not token:
        print(json.dumps(build_not_logged_in()))
        return

    cached = load_cache()
    cc_running = is_claude_code_running()

    if not force and is_cache_fresh(cached, ttl_minutes):
        if cached:
            cached["logged_in"] = True
            cached["cc_running"] = cc_running
            cached["cache_age_seconds"] = cache_age_seconds(cached)
            print(json.dumps(cached))
            return

    token, sub_type, token_err = ensure_valid_token()
    email = (cached or {}).get("email")
    if not email:
        auth = get_auth_status()
        if auth: 
            email = auth.get("email")
            sub_type = auth.get("subscriptionType", sub_type)

    try:
        result = fetch_usage(token)
        result.update({
            "logged_in": True, "subscription_type": sub_type,
            "email": email, "cc_running": cc_running, "cache_age_seconds": 0
        })
        save_cache(result)
        print(json.dumps(result))
    except urllib.error.HTTPError as e:
        error_msg_body = getattr(e, 'error_body', '')
        if e.code == 429:
            # If it passed fetch_usage without returning the 100% dict, it's definitely spam
            print(json.dumps({"error": "rate_limit_spam", "status": "too_fast", "api_msg": error_msg_body, "logged_in": True}))
        elif e.code in (401, 403):
            new_token, new_sub, refresh_err = ensure_valid_token(force_refresh=True)
            if new_token:
                try:
                    result = fetch_usage(new_token)
                    result.update({
                        "logged_in": True, "subscription_type": new_sub or sub_type,
                        "email": email, "cc_running": cc_running, "cache_age_seconds": 0
                    })
                    save_cache(result)
                    print(json.dumps(result))
                    return
                except Exception:
                    pass
            if cached:
                cached.update({"error": "token_expired", "logged_in": True, "cc_running": cc_running, "cache_age_seconds": cache_age_seconds(cached)})
                print(json.dumps(cached))
            else:
                out = build_not_logged_in()
                out["error"] = "token_expired"
                print(json.dumps(out))
        else:
            err_msg = f"api_error_{e.code}"
            print(json.dumps({"error": err_msg, "api_msg": error_msg_body, "logged_in": True}))
    except Exception as e:
        print(json.dumps({"error": str(e), "logged_in": True}))


if __name__ == "__main__":
    main()