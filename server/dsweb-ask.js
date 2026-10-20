#!/usr/bin/env node
// One-shot CLI: send a prompt to the local ds-web model, print the text.
// Used by the /ds-web slash command (bash pre-execution), so it works even
// when the host model cannot emit native tool_use.
const BASE = (process.env.DSWEB_BASE_URL || "http://127.0.0.1:15721").replace(/\/$/, "");
const KEY = process.env.DSWEB_KEY || "PROXY_MANAGED";
const MODEL = process.env.DSWEB_MODEL || "ds-web/deepseek-v4.1-flash";

const prompt = process.argv.slice(2).join(" ").trim();
if (!prompt) {
  console.error("usage: dsweb-ask.js <prompt>");
  process.exit(2);
}

const body = {
  model: MODEL,
  max_tokens: Number(process.env.DSWEB_MAX_TOKENS) > 0 ? Number(process.env.DSWEB_MAX_TOKENS) : 8192,
  messages: [{ role: "user", content: prompt }],
};

(async () => {
  const r = await fetch(BASE + "/v1/messages", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-api-key": KEY,
      authorization: "Bearer " + KEY,
      "anthropic-version": "2023-06-01",
    },
    body: JSON.stringify(body),
  });
  const raw = await r.text();
  if (!r.ok) {
    console.error(`upstream ${r.status}: ${raw.slice(0, 800)}`);
    process.exit(1);
  }
  let j;
  try {
    j = JSON.parse(raw);
  } catch {
    process.stdout.write(raw);
    return;
  }
  const text = (j.content || [])
    .filter((b) => b.type === "text")
    .map((b) => b.text)
    .join("\n");
  process.stdout.write(text || JSON.stringify(j));
})();