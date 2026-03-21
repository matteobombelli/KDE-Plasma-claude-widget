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

    # Default: fetch fresh data
    token, sub_type = read_credentials()
    if not token:
        print(json.dumps(build_not_logged_in()))
        return

    # Always resolve email: prefer cache, fall back to claude auth status
    cached = load_cache()
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
        # Fall back to cache on API error
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
