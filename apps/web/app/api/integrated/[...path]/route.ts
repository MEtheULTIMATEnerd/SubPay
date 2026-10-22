// Opt-in, authenticated integrated bridge. Never a general-purpose proxy.
const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const project = `projects/${UUID}`;
const contract = `${project}/contracts/${UUID}`;
const allowed: Record<string, RegExp> = {
  GET: new RegExp(`^(projects|${project}|${project}/contracts|${contract}|${contract}/items|${project}/evidence|${project}/evidence/${UUID}/observations|${project}/matches|${project}/claim-package\\.(json|html))$`),
  POST: new RegExp(`^(projects|${project}/contracts|${project}/evidence|${contract}/items/${UUID}/review|${project}/evidence/${UUID}/analyse|${project}/matches/generate|${project}/matches/${UUID}/(confirm|reject|reopen))$`),
  PATCH: new RegExp(`^${contract}/items/${UUID}$`),
};
const LIMIT = 21 * 1024 * 1024;
const reply = (status: number, detail: string) => Response.json({ detail }, { status, headers: { "Cache-Control": "no-store" } });

async function forward(request: Request, context: { params: Promise<{ path: string[] }> }) {
  if (process.env.SUBPAY_INTEGRATED_UI_ENABLED !== "true") return reply(404, "Local integration UI is disabled.");
  const host = request.headers.get("host") ?? "";
  if (!/^(localhost|127\.0\.0\.1):(3101|3102)$/.test(host)) return reply(403, "Approved loopback frontend required.");
  const origin = request.headers.get("origin");
  if (origin && origin !== `http://${host}`) return reply(403, "Same-origin requests only.");
  if (request.headers.get("sec-fetch-site") === "cross-site") return reply(403, "Same-origin requests only.");
  const authorization = request.headers.get("authorization") ?? "";
  if (!/^Bearer [\x21-\x7e]{32,}$/.test(authorization)) return reply(401, "Local access token required.");
  const { path } = await context.params;
  const target = path.join("/");
  if (!allowed[request.method]?.test(target) || new URL(request.url).search) return reply(404, "Route not available in local integration.");
  let body: Uint8Array | undefined;
  if (request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let length = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.length;
      if (length > LIMIT) { await reader.cancel(); return reply(413, "Upload exceeds local request limit."); }
      chunks.push(value);
    }
    body = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.length; }
  }
  try {
    const response = await fetch(`http://127.0.0.1:8000/api/v1/integrated/${target}`, {
      method: request.method, headers: { Authorization: authorization,
        ...(request.headers.get("content-type") ? { "Content-Type": request.headers.get("content-type")! } : {}) },
      body: body as BodyInit | undefined, cache: "no-store", redirect: "error", signal: AbortSignal.timeout(60000),
    });
    const headers = new Headers({ "Content-Type": response.headers.get("content-type") ?? "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    for (const name of ["content-disposition", "content-security-policy"]) {
      const value = response.headers.get(name); if (value) headers.set(name, value);
    }
    return new Response(await response.arrayBuffer(), { status: response.status, headers });
  } catch {
    return reply(502, "Local FastAPI is unavailable or timed out. Check the API before retrying an upload; it may already have been saved.");
  }
}
export { forward as GET, forward as POST, forward as PATCH };
