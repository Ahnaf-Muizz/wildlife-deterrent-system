#!/usr/bin/env python3
"""
Sentinel Wildlife Deterrent System - Jetson Orin Nano ESP32 Client
Communicates with the ESP32-S3 actuator node over HTTP (port 80 default, matching firmware)
or optional TLS proxy (--https).
Supports: GET /status and POST /command (BIRD, SMALL, LARGE, SOUND_TEST, WATER_TEST, LIGHT_TEST, STOP, SAFE, OFF)
"""

import json
import ssl
import urllib.request
import urllib.error
import argparse
from datetime import datetime, timezone

DEFAULT_HOST = "192.168.4.1"
DEFAULT_PORT = 80
DEFAULT_CA = "certs/dev_ca.crt"


def _build_base_url(host: str, port: int, use_https: bool) -> str:
    scheme = "https" if use_https else "http"
    return f"{scheme}://{host}:{port}"


def create_ssl_context(ca_path=None, insecure=False):
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    if ca_path:
        return ssl.create_default_context(cafile=ca_path)
    return ssl.create_default_context()


def get_status(host=DEFAULT_HOST, port=DEFAULT_PORT, use_https=False, ca_path=None, insecure=False):
    url = f"{_build_base_url(host, port, use_https)}/status"
    ctx = create_ssl_context(ca_path, insecure) if use_https else None
    req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            status_code = response.getcode()
            body = response.read().decode("utf-8")
            return status_code, json.loads(body)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")
    except Exception as e:
        return None, str(e)


def send_command(
    animal,
    request_id=None,
    host=DEFAULT_HOST,
    port=DEFAULT_PORT,
    use_https=False,
    ca_path=None,
    insecure=False,
):
    if request_id is None:
        request_id = f"orin-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')[:17]}"

    url = f"{_build_base_url(host, port, use_https)}/command"
    ctx = create_ssl_context(ca_path, insecure) if use_https else None

    payload = json.dumps({
        "animal": animal.upper(),
        "request_id": request_id,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            status_code = response.getcode()
            body = response.read().decode("utf-8")
            try:
                return status_code, json.loads(body)
            except Exception:
                return status_code, body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(body)
        except Exception:
            return e.code, body
    except Exception as e:
        return None, str(e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jetson Orin Nano to ESP32-S3 Client")
    parser.add_argument("--host", default=DEFAULT_HOST, help="ESP32 hostname or IP (default: 192.168.4.1)")
    parser.add_argument("--port", type=int, default=None, help="Port (default: 80 for HTTP, 443 for --https)")
    parser.add_argument("--https", action="store_true", help="Use HTTPS instead of HTTP")
    parser.add_argument("--ca", default=None, help="Path to dev_ca.crt")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS cert verification for testing")

    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.add_parser("status", help="Get ESP32 device status")

    cmd_parser = subparsers.add_parser("command", help="Send deterrent command")
    cmd_parser.add_argument(
        "animal",
        choices=["BIRD", "SMALL", "LARGE", "SOUND_TEST", "WATER_TEST", "LIGHT_TEST", "STOP", "SAFE", "OFF"],
        help="Target token",
    )
    cmd_parser.add_argument("--id", default=None, help="Custom request ID")

    args = parser.parse_args()
    port = args.port if args.port is not None else (443 if args.https else 80)

    if args.subcommand == "status":
        code, resp = get_status(args.host, port, args.https, args.ca, args.insecure)
        print(f"HTTP Status: {code}")
        print(json.dumps(resp, indent=2) if isinstance(resp, dict) else resp)
    elif args.subcommand == "command":
        code, resp = send_command(args.animal, args.id, args.host, port, args.https, args.ca, args.insecure)
        print(f"HTTP Status: {code}")
        print(json.dumps(resp, indent=2) if isinstance(resp, dict) else resp)
    else:
        parser.print_help()
