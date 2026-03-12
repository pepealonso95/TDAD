#!/usr/bin/env python3
"""Thin proxy that patches mlx_vlm.server responses for opencode compatibility.

mlx_vlm.server omits the required `index` field on tool_calls in streaming
responses. This proxy adds it so opencode's schema validation passes.

Handles both regular JSON responses and SSE (text/event-stream) responses.
"""

import json
import sys
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler

UPSTREAM = "http://127.0.0.1:7777"


class PatchingProxy(BaseHTTPRequestHandler):
    def do_GET(self):
        self._forward("GET")

    def do_POST(self):
        self._forward("POST")

    def _forward(self, method):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else None

        url = f"{UPSTREAM}{self.path}"
        headers = {"Content-Type": "application/json"} if body else {}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=600) as resp:
                raw = resp.read()
                content_type = resp.headers.get("Content-Type", "")

                if "text/event-stream" in content_type:
                    patched = _patch_sse(raw)
                else:
                    patched = _patch_json(raw)

                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() not in ("transfer-encoding", "content-length"):
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(patched)))
                self.end_headers()
                self.wfile.write(patched)
        except urllib.error.HTTPError as e:
            raw = e.read()
            self.send_response(e.code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    def log_message(self, format, *args):
        pass  # silence request logs


def _patch_sse(raw: bytes) -> bytes:
    """Patch tool_call indexes in SSE event stream lines."""
    text = raw.decode("utf-8", errors="replace")
    lines = text.split("\n")
    patched_lines = []
    changed = False

    for line in lines:
        if line.startswith("data: ") and line.strip() != "data: [DONE]":
            json_str = line[6:]  # strip "data: " prefix
            try:
                data = json.loads(json_str)
                if _patch_tool_calls(data):
                    line = "data: " + json.dumps(data)
                    changed = True
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        patched_lines.append(line)

    return "\n".join(patched_lines).encode("utf-8")


def _patch_json(raw: bytes) -> bytes:
    """Patch tool_call indexes in a regular JSON response."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw

    if _patch_tool_calls(data):
        return json.dumps(data).encode()
    return raw


def _patch_tool_calls(data: dict) -> bool:
    """Add missing 'index' field to tool_calls and fix finish_reason."""
    changed = False
    for choice in data.get("choices", []):
        for msg_key in ("message", "delta"):
            msg = choice.get(msg_key, {})
            if not msg:
                continue
            tool_calls = msg.get("tool_calls", [])
            for i, tc in enumerate(tool_calls):
                if "index" not in tc:
                    tc["index"] = i
                    changed = True
            # mlx_vlm always returns "stop" even when tool_calls are present.
            # OpenAI spec requires "tool_calls" as finish_reason in that case.
            if tool_calls and choice.get("finish_reason") == "stop":
                choice["finish_reason"] = "tool_calls"
                changed = True
    return changed


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    server = HTTPServer(("127.0.0.1", port), PatchingProxy)
    print(f"MLX proxy listening on http://127.0.0.1:{port} -> {UPSTREAM}")
    server.serve_forever()


if __name__ == "__main__":
    main()
