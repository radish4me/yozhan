// yozhan Gateway entrypoint. Phase 1 scope: health check + a thin proxy to the
// Agent Runtime's /chat endpoint, so the CLI smoke-test path has a Gateway
// hop it can later grow into pairing + channel adapters (Phase 5, see
// ARCHITECTURE.md section 3.1 and ROADMAP.md).

import express from "express";

const PORT = Number(process.env.PORT ?? 3000);
const RUNTIME_URL = process.env.RUNTIME_URL ?? "http://localhost:8787";

const app = express();
app.use(express.json());

app.get("/health", (_req, res) => {
  res.json({ status: "ok", runtime_url: RUNTIME_URL });
});

app.post("/chat", async (req, res) => {
  const response = await fetch(`${RUNTIME_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req.body),
  });
  const data = await response.json();
  res.status(response.status).json(data);
});

app.listen(PORT, () => {
  console.log(`yozhan gateway listening on :${PORT} (runtime: ${RUNTIME_URL})`);
});
