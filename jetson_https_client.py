#!/usr/bin/env python3
"""
Sentinel Wildlife Deterrent System - Jetson Orin Nano HTTPS Client
Communicates securely over TLS (TCP Port 443) with the ESP32-S3 actuator board.
Supports: GET /status and POST /command (TEST, RABBIT, RACCOON, DEER, BIRD, OFF)
"""

import sys
import json
import ssl
import urllib.request
import urllib.error
import argparse
from datetime import datetime

DEFAULT_HOST = "esp32.local"
DEFAULT_PORT = 443
DEFAULT_CA = "certs/dev_ca.crt"


def create_ssl_context(ca_path=None, insecure=False):
    if insecure:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    
    if ca_path:
        ctx = ssl.create_default_context(cafile=ca_path)
    else:
        ctx = ssl.create_default_context()
    return ctx


def get_status(host=DEFAULT_HOST, port=DEFAULT_PORT, ca_path=None, insecure=False):
    url = f"https://{host}:{port}/status"
    ctx = create_ssl_context(ca_path, insecure)
    req = urllib.request.Request(url, method="GET")
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            status_code = response.getcode()
            body = response.read().decode('utf-8')
            return status_code, json.loads(body)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except Exception as e:
        return None, str(e)


def send_command(animal, request_id=None, host=DEFAULT_HOST, port=DEFAULT_PORT, ca_path=None, insecure=False):
    if request_id is None:
        request_id = f"orin-{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')[:17]}"
        
    url = f"https://{host}:{port}/command"
    ctx = create_ssl_context(ca_path, insecure)
    
    payload = json.dumps({
        "animal": animal.upper(),
        "request_id": request_id
    }).encode('utf-8')
    
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=5) as response:
            status_code = response.getcode()
            body = response.read().decode('utf-8')
            try:
                return status_code, json.loads(body)
            except:
                return status_code, body
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        try:
            return e.code, json.loads(body)
        except:
            return e.code, body
    except Exception as e:
        return None, str(e)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Jetson Orin Nano to ESP32-S3 HTTPS Client")
    parser.add_argument("--host", default=DEFAULT_HOST, help="ESP32 hostname or IP (default: esp32.local)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="HTTPS port (default: 443)")
    parser.add_argument("--ca", default=None, help="Path to dev_ca.crt")
    parser.add_argument("--insecure", action="store_true", help="Disable TLS cert verification for testing")
    
    subparsers = parser.add_subparsers(dest="subcommand")
    subparsers.add_parser("status", help="Get ESP32 device status")
    
    cmd_parser = subparsers.add_parser("command", help="Send deterrent command")
    cmd_parser.add_argument("animal", choices=["TEST", "RABBIT", "RACCOON", "DEER", "BIRD", "OFF"], help="Target token")
    cmd_parser.add_argument("--id", default=None, help="Custom request ID")
    
    args = parser.parse_args()
    
    if args.subcommand == "status":
        code, resp = get_status(args.host, args.port, args.ca, args.insecure)
        print(f"HTTP Status: {code}")
        print(json.dumps(resp, indent=2) if isinstance(resp, dict) else resp)
    elif args.subcommand == "command":
        code, resp = send_command(args.animal, args.id, args.host, args.port, args.ca, args.insecure)
        print(f"HTTP Status: {code}")
        print(json.dumps(resp, indent=2) if isinstance(resp, dict) else resp)
    else:
        parser.print_help()
