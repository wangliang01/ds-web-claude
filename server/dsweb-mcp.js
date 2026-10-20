#!/usr/bin/env node
// Minimal stdio MCP server exposing ds_web: one-shot prompt to the local
// ds-web model (cc-switch proxy on 15721, Anthropic Messages API). Stdlib only.
const BASE = process.env.DSWEB_BASE_URL || "http://127.0.0.1:15721";
const KEY = process.env.DSWEB_KEY || "PROXY_MANAGED";
const MODEL = process.env.DSWEB_MODEL || "ds-web/deepseek-v4.1-flash";

async function ask({ prompt, system, model, max_tokens } = {}) {
  if (!prompt || typeof prompt !== "string") throw new Error("prompt is required");
  const body = {
    model: model || MODEL,
    max_tokens: Number(max_tokens) > 0 ? Number(max_tokens) : 8192,
    messages: [{ role: "user", content: prompt }],
  };
  if (system) body.system = String(system);
  const r = await fetch(BASE.replace(/\/$/, "") + "/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": KEY,
      authorization: "Bearer " + KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify(body),
  });
  const text = await r.text();
  if (!r.ok) throw new Error(`upstream ${r.status}: ${text.slice(0, 800)}`);
  let j;
  try { j = JSON.parse(text); } catch { return text; }
  const out = (j.content || []).filter((b) => b.type === "text").map((b) => b.text).join("\n");
  return out || JSON.stringify(j);
}

const TOOL = {
  name: "ds_web",
  description:
    "Delegate a self-contained task to the local ds-web model (DeepSeek via cc-switch proxy). " +
    "Use for bulk/mechanical work, second opinions, or when a cheap model suffices. " +
    "The model sees ONLY this prompt: include all needed context. No tools, no filesystem, one turn.",
  inputSchema: {
    type: "object",
    properties: {
      prompt: { type: "string", description: "Full self-contained task/context." },
      system: { type: "string", description: "Optional system instruction." },
      model: { type: "string", description: `Override model. Default: ${MODEL}` },
      max_tokens: { type: "number", description: "Default 8192." },
    },
    required: ["prompt"],
  },
};

const send = (msg) => process.stdout.write(JSON.stringify(msg) + "\n");

async function handle(msg) {
  const { id, method, params } = msg;
  if (method === "initialize") {
    return send({
      jsonrpc: "2.0", id,
      result: {
        protocolVersion: params?.protocolVersion || "2024-11-05",
        capabilities: { tools: {} },
        serverInfo: { name: "ds-web", version: "1.0.0" },
      },
    });
  }
  if (method === "notifications/initialized") return;
  if (method === "tools/list") return send({ jsonrpc: "2.0", id, result: { tools: [TOOL] } });
  if (method === "tools/call") {
    const name = params?.name;
    if (name !== "ds_web") {
      return send({ jsonrpc: "2.0", id, result: { isError: true, content: [{ type: "text", text: `unknown tool: ${name}` }] } });
    }
    try {
      const out = await ask(params?.arguments || {});
      return send({ jsonrpc: "2.0", id, result: { content: [{ type: "text", text: out }] } });
    } catch (e) {
      return send({ jsonrpc: "2.0", id, result: { isError: true, content: [{ type: "text", text: String(e.message || e) }] } });
    }
  }
  if (method === "ping") return send({ jsonrpc: "2.0", id, result: {} });
  if (id !== undefined && id !== null) {
    send({ jsonrpc: "2.0", id, error: { code: -32601, message: `method not found: ${method}` } });
  }
}

let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buf += chunk;
  let i;
  while ((i = buf.indexOf("\n")) >= 0) {
    const line = buf.slice(0, i).trim();
    buf = buf.slice(i + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { continue; }
    Promise.resolve(handle(msg)).catch((e) => {
      if (msg?.id !== undefined) send({ jsonrpc: "2.0", id: msg.id, error: { code: -32603, message: String(e.message || e) } });
    });
  }
});