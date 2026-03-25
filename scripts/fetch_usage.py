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
TOKEN_EXPIRY_BUFFER_MS = 5 * 60 * 1000  # refresh 5 minutes before expiry
OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"

_debug_enabled = False
_claude_version_cache = None


def _get_claude_version():
    """Return the installed claude-code version string (cached)."""
    global _claude_version_cache
    if _claude_version_cache:
        return _claude_version_cache
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        # output: "2.1.81 (Claude Code)"
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
    remaining_ms = expires_at - now_ms
    debug_log(f"Token expiresAt={expires_at}, now={now_ms}, remaining={remaining_ms}ms, buffer={TOKEN_EXPIRY_BUFFER_MS}ms")
    return now_ms >= (expires_at - TOKEN_EXPIRY_BUFFER_MS)


def refresh_token():
    """Refresh the OAuth access token using the refresh token.
    Returns (new_token, subscription_type, error_msg) — error_msg is None on success."""
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
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        msg = f"token refresh HTTP {e.code}: {body}"
        debug_log(f"refresh_token failed: {msg}")
        return None, None, msg
    except Exception as e:
        msg = f"token refresh error: {e}"
        debug_log(f"refresh_token failed: {msg}")
        return None, None, msg

    new_access = data.get("access_token")
    if not new_access:
        msg = f"token refresh response missing access_token: {list(data.keys())}"
        debug_log(f"refresh_token failed: {msg}")
        return None, None, msg

    oauth["accessToken"] = new_access
    if "refresh_token" in data:
        oauth["refreshToken"] = data["refresh_token"]
    if "expires_in" in data:
        oauth["expiresAt"] = int(time.time() * 1000) + data["expires_in"] * 1000

    creds["claudeAiOauth"] = oauth
    try:
        with open(CREDENTIALS_PATH, "w") as f:
            json.dump(creds, f, indent=2)
    except OSError as e:
        debug_log(f"refresh_token: failed to write credentials: {e}")

    debug_log("refresh_token: success, new token written")
    return new_access, oauth.get("subscriptionType", "unknown"), None


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


def ensure_valid_token(force_refresh=False):
    """Return a valid (token, subscription_type, error_msg), refreshing if needed."""
    token, sub_type = read_credentials()
    if not token:
        return None, None, "no credentials found"

    if force_refresh or is_token_expired():
        debug_log(f"Token refresh needed (force={force_refresh}, expired={is_token_expired()})")
        new_token, new_sub, err = refresh_token()
        if new_token:
            return new_token, new_sub, None
        debug_log(f"Token refresh failed: {err}; falling through to existing token")
        return token, sub_type, err  # return old token + error so caller can decide

    return token, sub_type, None


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

    try:
        resp = urllib.request.urlopen(req, timeout=15)
        status_code = resp.status
    except urllib.error.HTTPError as e:
        status_code = e.code
        debug_log(f"fetch_usage HTTP error {e.code}")
        raise
    finally:
        debug_log(f"fetch_usage API call status: {status_code}")

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


def cache_age_seconds(cached):
    """Return seconds since the cached data was written, or None."""
    if not cached:
        return None
    ts = cached.get("timestamp")
    if ts is None:
        return None
    return int(time.time() - ts)


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

    # Parse --ttl argument (default: 5 minutes)
    ttl_minutes = 5
    if "--ttl" in sys.argv:
        idx = sys.argv.index("--ttl")
        if idx + 1 < len(sys.argv):
            try:
                ttl_minutes = max(1, int(sys.argv[idx + 1]))
            except ValueError:
                pass

    debug_log(f"fetch_usage.py args: {sys.argv[1:]}")

    # --refresh-token: only refresh the OAuth token, no API call
    if "--refresh-token" in sys.argv:
        token, sub_type = read_credentials()
        if not token:
            print(json.dumps({"refreshed": False, "error": "no credentials"}))
            return
        _, _, err = refresh_token()
        if err:
            print(json.dumps({"refreshed": False, "error": err}))
        else:
            print(json.dumps({"refreshed": True}))
        return

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
            cached["cache_age_seconds"] = cache_age_seconds(cached)
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
    cc_running = is_claude_code_running()
    debug_log(f"cc_running={cc_running}, force={force}, ttl_minutes={ttl_minutes}")

    effective_ttl = ttl_minutes

    # Serve from cache if still within the effective TTL window — unless --force is set
    if not force and is_cache_fresh(cached, effective_ttl):
        if cached:
            cached["logged_in"] = True
            cached["subscription_type"] = sub_type
            cached["cc_running"] = cc_running
            cached["cache_age_seconds"] = cache_age_seconds(cached)
            if not cached.get("email"):
                auth = get_auth_status()
                if auth:
                    cached["email"] = auth.get("email")
                    cached["subscription_type"] = auth.get("subscriptionType", sub_type)
            print(json.dumps(cached))
            return

    # Cache is stale — refresh token and call API
    token, sub_type, token_err = ensure_valid_token()
    if not token:
        # Complete token failure — return stale cache with token_expired error if available
        if cached:
            cached["error"] = "token_expired"
            cached["logged_in"] = True
            cached["cc_running"] = cc_running
            cached["cache_age_seconds"] = cache_age_seconds(cached)
            print(json.dumps(cached))
        else:
            out = build_not_logged_in()
            out["error"] = "token_expired"
            print(json.dumps(out))
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
        result["cc_running"] = cc_running
        result["cache_age_seconds"] = 0
        save_cache(result)
        print(json.dumps(result))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            # Token was rejected — force-refresh and retry once
            debug_log(f"API call returned {e.code}, force-refreshing token and retrying")
            new_token, new_sub, refresh_err = ensure_valid_token(force_refresh=True)
            if new_token:
                try:
                    result = fetch_usage(new_token)
                    result["logged_in"] = True
                    result["subscription_type"] = new_sub or sub_type
                    result["email"] = email
                    result["cc_running"] = cc_running
                    result["cache_age_seconds"] = 0
                    save_cache(result)
                    print(json.dumps(result))
                    return
                except Exception as retry_e:
                    debug_log(f"API call retry failed: {retry_e}")
            # Both attempts failed — treat as token expired
            if cached:
                cached["error"] = "token_expired"
                cached["logged_in"] = True
                cached["cc_running"] = cc_running
                cached["cache_age_seconds"] = cache_age_seconds(cached)
                print(json.dumps(cached))
            else:
                out = build_not_logged_in()
                out["error"] = "token_expired"
                print(json.dumps(out))
        else:
            # Non-auth HTTP error — return stale cache with api_error
            err_msg = f"api_error_{e.code}"
            debug_log(f"API call failed: {err_msg}")
            if cached:
                cached["error"] = err_msg
                cached["logged_in"] = True
                cached["cc_running"] = cc_running
                cached["cache_age_seconds"] = cache_age_seconds(cached)
                print(json.dumps(cached))
            else:
                out = build_not_logged_in()
                out["error"] = err_msg
                out["logged_in"] = True
                out["subscription_type"] = sub_type
                out["email"] = email
                out["timestamp"] = int(time.time())
                print(json.dumps(out))
    except Exception as e:
        debug_log(f"API call exception: {e}")
        if cached:
            cached["error"] = str(e)
            cached["logged_in"] = True
            cached["cc_running"] = cc_running
            cached["cache_age_seconds"] = cache_age_seconds(cached)
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
