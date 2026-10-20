#!/usr/bin/env python3
"""Anthropic passthrough proxy that repairs DSML tool-call leaks.

Upstream must speak the Anthropic Messages API (cc-switch on 15721 does).
The ds-web model emits tool calls as DSML text instead of native tool_use
blocks; this proxy converts them. Streaming is synthesized from a buffered
upstream response so repair happens before anything reaches the client.
Stdlib only.
"""
import json, os, re, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlreq, error as urlerr

UPSTREAM = os.environ.get("DSWEB_UPSTREAM", "http://127.0.0.1:15721").rstrip("/")
UPSTREAM_KEY = os.environ.get("DSWEB_KEY", "PROXY_MANAGED")
LISTEN = int(os.environ.get("DSWEB_PORT", "15722"))
MODELS = [
    "claude-fable-5", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5",
    "claude-fable-5[1M]", "claude-opus-5[1M]", "claude-sonnet-5[1M]",
]

_SEP = r"(?:\uff5c{1,2}DSML\uff5c{1,2}|\|{1,2}DSML\|{1,2})"
_OUTER = re.compile(r"<\s*" + _SEP + r"\s*(?:tool_calls|function_calls|calls)\s*>([\s\S]*?)<\s*/\s*" + _SEP + r"\s*(?:tool_calls|function_calls|calls)\s*>", re.I)
_INVOKE = re.compile(r"<\s*" + _SEP + r"\s*invoke\s+name=[\"']([^\"']+)[\"']\s*>", re.I)
_PARAM = re.compile(r"<\s*" + _SEP + r"\s*parameter\s+name=[\"']([^\"']+)[\"'](?:\s+string=[\"'](true|false)[\"'])?\s*>([\s\S]*?)<\s*/\s*" + _SEP + r"\s*parameter\s*>", re.I)
_MARKER = re.compile(r"</?\s*" + _SEP + r"\s*(?:tool_calls|function_calls|calls|invoke|parameter)(?:\s+[^>\n]*)?>?", re.I)

TOOL_MAP = {"bash": "Bash", "read": "Read", "write": "Write", "edit": "Edit",
            "grep": "Grep", "glob": "Glob", "webfetch": "WebFetch", "task": "Task",
            "todowrite": "TodoWrite", "notebookedit": "NotebookEdit", "skill": "Skill"}


def map_tool(n):
    return TOOL_MAP.get((n or "").lower(), n)


def _maybe_json(s):
    try:
        return json.loads(s)
    except Exception:
        return s


def _args(body, start):
    out = {}
    for pm in _PARAM.finditer(body[start:]):
        key, is_str, raw = pm.group(1).strip(), pm.group(2), pm.group(3)
        out[key] = raw if is_str == "true" else _maybe_json(raw.strip())
    return out


def parse_dsml(text):
    """Return (clean_text, [{name, arguments}])."""
    if "DSML" not in text:
        return text, []
    calls = []

    def take(m):
        body = m.group(1)
        for inv in _INVOKE.finditer(body):
            name = inv.group(1).strip()
            if name:
                calls.append({"name": name, "arguments": _args(body, inv.end())})
        return ""

    clean = _OUTER.sub(take, text)
    if not calls:
        invs = list(_INVOKE.finditer(clean))
        for i, inv in enumerate(invs):
            name = inv.group(1).strip()
            end = invs[i + 1].start() if i + 1 < len(invs) else len(clean)
            if name:
                calls.append({"name": name, "arguments": _args(clean[inv.end():end], 0)})
    if calls or _MARKER.search(clean):
        clean = _MARKER.sub("", clean)
    return clean.strip(), calls


TOOL_HINT = """
You can call tools. To call a tool, output ONLY this exact block (no markdown fence):

<\uff5c\uff5cDSML\uff5c\uff5c calls>
<\uff5c\uff5cDSML\uff5c\uff5c invoke name="ToolName">
<\uff5c\uff5cDSML\uff5c\uff5c parameter name="param" string="true">value<\uff5c\uff5cDSML\uff5c\uff5c parameter>
<\uff5c\uff5cDSML\uff5c\uff5c invoke>
<\uff5c\uff5cDSML\uff5c\uff5c calls>

Use string="false" for numbers, booleans, arrays and objects (JSON body).
Emit nothing else when calling a tool. Available tools:

"""


def inject_tools(payload):
    """Put the client's tool schemas into the system prompt; upstream drops `tools`."""
    tools = payload.get("tools")
    if not tools:
        return
    lines = []
    for t in tools:
        schema = t.get("input_schema") or t.get("parameters") or {}
        lines.append("- " + str(t.get("name")) + ": " + (t.get("description") or "").strip())
        lines.append("  input schema: " + json.dumps(schema, ensure_ascii=False))
    hint = TOOL_HINT + "\n".join(lines)
    sysp = payload.get("system")
    if isinstance(sysp, list):
        payload["system"] = sysp + [{"type": "text", "text": hint}]
    elif isinstance(sysp, str) and sysp:
        payload["system"] = sysp + hint
    else:
        payload["system"] = hint
    payload.pop("tools", None)
    payload.pop("tool_choice", None)


def repair(up, model_in):
    """Turn an upstream Anthropic message into a leak-free one."""
    blocks, calls = [], []
    for b in up.get("content") or []:
        if b.get("type") == "text":
            clean, found = parse_dsml(b.get("text") or "")
            if clean:
                blocks.append({"type": "text", "text": clean})
            calls.extend(found)
        elif b.get("type") == "tool_use":
            blocks.append(b)
    for c in calls:
        blocks.append({
            "type": "tool_use",
            "id": "toolu_" + uuid.uuid4().hex[:24],
            "name": map_tool(c["name"]),
            "input": c["arguments"] if isinstance(c["arguments"], dict) else {},
        })
    stop = "tool_use" if any(b.get("type") == "tool_use" for b in blocks) else (up.get("stop_reason") or "end_turn")
    return {
        "id": up.get("id") or "msg_" + uuid.uuid4().hex[:20],
        "type": "message",
        "role": "assistant",
        "model": model_in or up.get("model") or "",
        "content": blocks or [{"type": "text", "text": ""}],
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": up.get("usage") or {"input_tokens": 0, "output_tokens": 0},
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0].rstrip("/")
        if p.endswith("/models"):
            return self._send(200, {"data": [{"id": m, "type": "model", "display_name": m} for m in MODELS]})
        return self._send(200, {"ok": True})

    def do_POST(self):
        p = self.path.split("?")[0].rstrip("/")
        if not (p.endswith("/messages") or p.endswith("/messages/count_tokens")):
            return self._send(404, {"error": "not found"})
        n = int(self.headers.get("content-length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception as e:
            return self._send(400, {"type": "error", "error": {"type": "invalid_request_error", "message": str(e)}})
        if p.endswith("count_tokens"):
            return self._send(200, {"input_tokens": 0})

        want_stream = bool(body.get("stream"))
        payload = dict(body)
        payload["stream"] = False
        payload.pop("stream_options", None)
        inject_tools(payload)

        req = urlreq.Request(
            UPSTREAM + "/v1/messages",
            data=json.dumps(payload).encode(),
            headers={
                "content-type": "application/json",
                "authorization": "Bearer " + UPSTREAM_KEY,
                "x-api-key": UPSTREAM_KEY,
                "anthropic-version": self.headers.get("anthropic-version") or "2023-06-01",
            },
        )
        try:
            r = urlreq.urlopen(req, timeout=600)
            up = json.loads(r.read() or b"{}")
        except urlerr.HTTPError as e:
            return self._send(e.code, {"type": "error", "error": {"type": "api_error", "message": e.read().decode(errors="replace")}})
        except Exception as e:
            return self._send(502, {"type": "error", "error": {"type": "api_error", "message": str(e)}})

        msg = repair(up, body.get("model"))
        if not want_stream:
            return self._send(200, msg)
        self._emit_sse(msg)

    def _emit_sse(self, msg):
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("connection", "close")
        self.close_connection = True
        self.end_headers()

        def emit(ev, data):
            self.wfile.write(("event: " + ev + "\ndata: " + json.dumps(data, ensure_ascii=False) + "\n\n").encode())
            self.wfile.flush()

        emit("message_start", {"type": "message_start", "message": {
            "id": msg["id"], "type": "message", "role": "assistant",
            "model": msg["model"], "content": [], "stop_reason": None,
            "stop_sequence": None, "usage": msg["usage"],
        }})
        for i, b in enumerate(msg["content"]):
            if b.get("type") == "text":
                emit("content_block_start", {"type": "content_block_start", "index": i,
                                             "content_block": {"type": "text", "text": ""}})
                emit("content_block_delta", {"type": "content_block_delta", "index": i,
                                             "delta": {"type": "text_delta", "text": b["text"]}})
            else:
                emit("content_block_start", {"type": "content_block_start", "index": i,
                                             "content_block": {"type": "tool_use", "id": b["id"],
                                                               "name": b["name"], "input": {}}})
                emit("content_block_delta", {"type": "content_block_delta", "index": i,
                                             "delta": {"type": "input_json_delta",
                                                       "partial_json": json.dumps(b["input"], ensure_ascii=False)}})
            emit("content_block_stop", {"type": "content_block_stop", "index": i})
        emit("message_delta", {"type": "message_delta",
                               "delta": {"stop_reason": msg["stop_reason"], "stop_sequence": None},
                               "usage": msg["usage"]})
        emit("message_stop", {"type": "message_stop"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", LISTEN), Handler)
    print(f"ds-web repair proxy on 127.0.0.1:{LISTEN} -> {UPSTREAM}", flush=True)
    srv.serve_forever()