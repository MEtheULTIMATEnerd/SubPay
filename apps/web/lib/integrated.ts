// Isolated local API client. No demo store, browser storage or AI requests.
export type LocalProject = {
  id: string; name: string; description: string; created_at: string; updated_at: string;
};
export type LocalContract = {
  id: string; original_filename: string; created_at: string; limitation: string | null;
  extracted_text: string;
};
export type LocalItem = {
  id: string; description: string; source_reference: string; item_code: string;
  quantity: number | null; unit: string | null; rate: number | null; amount: number | null;
  review_status: "draft" | "confirmed" | "rejected";
  reviewed_by: string | null; reviewed_at: string | null; updated_at: string;
};
export type LocalEvidence = {
  id: string; original_filename: string; uploaded_at: string; content_type: string;
  size: number; processing_status: "uploaded" | "processing" | "ready" | "failed";
};
export type LocalAnalysis = {
  id: string; provider: string; model: string; processed_at: string | null;
  status: string; error: string | null;
  structured_data: null | { mock: boolean; observations: Record<string, string[]> };
};
export type LocalMatch = {
  id: string; evidence_id: string; item_description: string; score: number;
  explanation: string; is_current: boolean; review_status: "pending" | "confirmed" | "rejected";
  observation_provider: string; observation_model: string;
  supporting_observations: { group: string; text: string }[];
  reviewed_by: string | null; reviewed_at: string | null;
};

export class IntegratedError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export function integratedClient(token: string) {
  const analysing = new Set<string>();
  if (token.length < 32 || !/^[\x21-\x7e]+$/.test(token)) {
    throw new IntegratedError(401, "Enter the configured local access token (at least 32 ASCII characters).");
  }
  async function responseFor(path: string, method = "GET", body?: object | FormData): Promise<Response> {
    let response: Response;
    const multipart = body instanceof FormData;
    try {
      response = await fetch(`/api/integrated/${path}`, {
        method, cache: "no-store", credentials: "omit",
        headers: { Authorization: `Bearer ${token}`, ...(body && !multipart ? { "Content-Type": "application/json" } : {}) },
        body: body ? (multipart ? body : JSON.stringify(body)) : undefined,
      });
    } catch {
      throw new IntegratedError(0, "Cannot reach the local server. Check that Next.js and FastAPI are running.");
    }
    if (!response.ok) {
      const data = await response.json().catch(() => null);
      const detail = typeof data?.detail === "string" ? data.detail : "Check the submitted fields and file format.";
      throw new IntegratedError(response.status, response.status === 401
        ? "Authentication failed. Disconnect and enter the configured local access token."
        : `${response.status}: ${detail}`);
    }
    return response;
  }
  async function request<T>(path: string, method = "GET", body?: object | FormData): Promise<T> {
    return (await responseFor(path, method, body)).json() as Promise<T>;
  }
  function upload<T>(path: string, file: File) {
    const form = new FormData();
    form.append("file", file);
    return request<T>(path, "POST", form);
  }
  const contracts = (pid: string) => `projects/${pid}/contracts`;
  const items = (pid: string, cid: string) => `${contracts(pid)}/${cid}/items`;
  return {
    projects: () => request<LocalProject[]>("projects"),
    createProject: (name: string, description: string) => request<LocalProject>("projects", "POST", { name: name.trim(), description }),
    project: (pid: string) => request<LocalProject>(`projects/${pid}`),
    contracts: (pid: string) => request<LocalContract[]>(contracts(pid)),
    contract: (pid: string, cid: string) => request<LocalContract>(`${contracts(pid)}/${cid}`),
    uploadContract: (pid: string, file: File) => upload<LocalContract>(contracts(pid), file),
    items: (pid: string, cid: string) => request<LocalItem[]>(items(pid, cid)),
    editItem: (pid: string, cid: string, iid: string, description: string) => request<LocalItem>(`${items(pid, cid)}/${iid}`, "PATCH", { description }),
    reviewItem: (pid: string, cid: string, iid: string, status: LocalItem["review_status"]) => request<LocalItem>(`${items(pid, cid)}/${iid}/review`, "POST", { status }),
    deleteContract: async (pid: string, cid: string) => { await responseFor(`${contracts(pid)}/${cid}`, "DELETE"); },
    deleteItem: async (pid: string, cid: string, iid: string) => { await responseFor(`${items(pid, cid)}/${iid}`, "DELETE"); },
    evidence: (pid: string) => request<LocalEvidence[]>(`projects/${pid}/evidence`),
    uploadEvidence: (pid: string, file: File) => upload<LocalEvidence>(`projects/${pid}/evidence`, file),
    observations: (pid: string, eid: string) => request<LocalAnalysis[]>(`projects/${pid}/evidence/${eid}/observations`),
    analyse: async (pid: string, eid: string, consent: () => boolean) => {
      const key = `${pid}/${eid}`;
      if (analysing.has(key)) return;
      analysing.add(key);
      try {
        if (!consent()) return;
        return await request<LocalAnalysis>(`projects/${pid}/evidence/${eid}/analyse`, "POST");
      } finally { analysing.delete(key); }
    },
    matches: (pid: string) => request<LocalMatch[]>(`projects/${pid}/matches`),
    generateMatches: (pid: string) => request<{ created: number }>(`projects/${pid}/matches/generate`, "POST"),
    reviewMatch: (pid: string, mid: string, action: "confirm" | "reject" | "reopen") => request<LocalMatch>(`projects/${pid}/matches/${mid}/${action}`, "POST"),
    package: async (pid: string, format: "json" | "html") => (await responseFor(`projects/${pid}/claim-package.${format}`)).blob(),
  };
}
