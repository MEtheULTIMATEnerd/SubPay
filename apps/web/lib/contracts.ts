// Contracts and their claim line items (F03 to F05). Components call these
// functions and never talk to the API or the mock directly.
//
// live mode: files and records live behind the FastAPI service. The local
//            store keeps a copy of a project's contracts and items so pages
//            (and the features still on mock data) can read them at once.
// demo mode: the original prototype behaviour, simulated in lib/api.ts.
import * as mock from "./api";
import { LIVE } from "./env";
import { ApiError, isApiError } from "./errors";
import { apiFetch } from "./http";
import { commit, getDb } from "./store";
import type { Contract, ContractItem } from "./types";

export type ItemPatch = Partial<
  Pick<ContractItem, "description" | "quantity" | "unit" | "rate" | "amount" | "conditions" | "notice_requirement" | "due_date">
>;
export type ReviewAction = "confirmed" | "rejected" | "draft";

const POLL_MS = 1500;
const MAX_POLLS = 120; // about three minutes

// ---------- the local copy ----------
function storeContract(contract: Contract) {
  commit((d) => {
    const index = d.contracts.findIndex((c) => c.id === contract.id);
    if (index === -1) d.contracts.unshift(contract);
    else d.contracts[index] = contract;
  });
}

function storeItems(contractId: string, items: ContractItem[]) {
  commit((d) => {
    d.contract_items = [...d.contract_items.filter((i) => i.contract_id !== contractId), ...items];
  });
}

function storeItem(item: ContractItem) {
  commit((d) => {
    const index = d.contract_items.findIndex((i) => i.id === item.id);
    if (index === -1) d.contract_items.push(item);
    else d.contract_items[index] = item;
  });
}

/** The API's contract detail carries a short-lived link that must not be kept. */
function withoutLink(contract: Contract & { download_url?: string | null }): Contract {
  const copy = { ...contract };
  delete copy.download_url;
  return copy;
}

// ---------- reading ----------
/** Replace the local copy of this project's contracts and items with what the API returns. */
export async function refreshContracts(projectId: string): Promise<void> {
  if (!LIVE) return;
  const { items: contracts } = await apiFetch<{ items: Contract[] }>(`/projects/${projectId}/contracts`);
  const lists = await Promise.all(contracts.map((c) => apiFetch<{ items: ContractItem[] }>(`/contracts/${c.id}/items`)));
  commit((d) => {
    const stale = new Set(d.contracts.filter((c) => c.project_id === projectId).map((c) => c.id));
    contracts.forEach((c) => stale.add(c.id));
    d.contracts = [...d.contracts.filter((c) => c.project_id !== projectId), ...contracts];
    d.contract_items = [...d.contract_items.filter((i) => !stale.has(i.contract_id)), ...lists.flatMap((l) => l.items)];
  });
  contracts.filter((c) => c.processing_status === "processing").forEach((c) => watchExtraction(c.id));
}

/** A fresh, short-lived link to the stored document. Null in demo mode, where files are not stored. */
export async function getContractDownloadUrl(contractId: string): Promise<string | null> {
  if (!LIVE) return null;
  const contract = await apiFetch<Contract & { download_url: string | null }>(`/contracts/${contractId}`);
  return contract.download_url;
}

// ---------- upload and extraction ----------
/**
 * Returns the new contract's id. Extraction then runs on its own; the page updates when it finishes.
 * `onProgress` is called with how much of the file has been sent, from 0 to 1.
 */
export async function uploadContract(projectId: string, file: File, onProgress?: (fraction: number) => void): Promise<string> {
  if (!LIVE) {
    const id = mock.uploadContract(projectId, file);
    onProgress?.(1); // nothing is sent anywhere in demo mode
    return id;
  }

  // The API checks the file's real contents. These are the same rules, for an instant answer.
  if (!mock.CONTRACT_TYPES.includes(file.type) && !/\.(pdf|docx)$/i.test(file.name)) {
    throw new ApiError(415, "Only PDF or DOCX contracts are supported", "unsupported_media_type");
  }
  if (file.size > mock.MAX_CONTRACT_BYTES) throw new ApiError(413, "Contract must be 25 MB or smaller", "payload_too_large");

  const form = new FormData();
  form.append("file", file, file.name);
  const contract = await apiFetch<Contract>(`/projects/${projectId}/contracts`, { method: "POST", form, onUploadProgress: onProgress });
  onProgress?.(1);
  storeContract(contract);
  mock.logAudit(projectId, "contract.uploaded", "contract", contract.id, { filename: contract.original_filename });
  watchExtraction(contract.id);
  return contract.id;
}

/** Start extraction again after a failure. */
export async function retryExtraction(contractId: string): Promise<void> {
  if (!LIVE) return mock.startExtraction(contractId);
  storeContract(await apiFetch<Contract>(`/contracts/${contractId}/extract`, { method: "POST" }));
  watchExtraction(contractId);
}

const watching = new Set<string>();

/** Follow a contract until extraction is ready or has failed, then load its items. */
function watchExtraction(contractId: string) {
  if (watching.has(contractId)) return;
  watching.add(contractId);
  let polls = 0;

  const check = async () => {
    polls += 1;
    try {
      const contract = withoutLink(await apiFetch<Contract>(`/contracts/${contractId}`));
      if (contract.processing_status === "ready") {
        const { items } = await apiFetch<{ items: ContractItem[] }>(`/contracts/${contractId}/items`);
        storeItems(contractId, items);
        storeContract(contract);
        mock.logAudit(contract.project_id, "contract.extracted", "contract", contractId, { items: items.length }, true);
        mock.notifyTeam(
          contract.project_id,
          "Claim schedule ready for review",
          `${items.length} items extracted from ${contract.original_filename}.`,
          `/projects/${contract.project_id}/contracts/${contractId}/items`,
        );
        watching.delete(contractId);
        return;
      }
      storeContract(contract);
      if (contract.processing_status === "failed") {
        watching.delete(contractId);
        return;
      }
    } catch (err) {
      // Gone, or the session ended: stop. Anything else (a blip) is worth another try.
      if (isApiError(err) && (err.status === 404 || err.status === 401)) {
        watching.delete(contractId);
        return;
      }
    }
    if (polls >= MAX_POLLS) {
      watching.delete(contractId);
      return;
    }
    setTimeout(() => void check(), POLL_MS);
  };
  setTimeout(() => void check(), POLL_MS);
}

// ---------- human review ----------
const projectOf = (item: ContractItem) => getDb().contracts.find((c) => c.id === item.contract_id)?.project_id ?? null;

/** Save a person's corrections. Only fields that actually changed are sent. */
export async function updateContractItem(id: string, patch: ItemPatch): Promise<void> {
  if (!LIVE) return mock.updateContractItem(id, patch);
  const current = getDb().contract_items.find((i) => i.id === id);
  if (!current) throw new ApiError(404, "Contract item not found", "not_found");

  const fields = (Object.keys(patch) as (keyof ItemPatch)[]).filter((k) => patch[k] !== current[k]);
  if (!fields.length) return;
  const changes = Object.fromEntries(fields.map((k) => [k, patch[k]]));
  const before = Object.fromEntries(fields.map((k) => [k, current[k]]));

  const item = await apiFetch<ContractItem>(`/contract-items/${id}`, { method: "PATCH", body: changes });
  storeItem(item);
  mock.logAudit(projectOf(item), "contract_item.edited", "contract_item", id, { item: item.item_code, fields, before });
}

/** Confirm, reject, or return an item to draft. */
export async function reviewContractItem(id: string, status: ReviewAction): Promise<void> {
  if (!LIVE) return mock.reviewContractItem(id, status);
  const action = status === "confirmed" ? "confirm" : status === "rejected" ? "reject" : "reopen";
  const item = await apiFetch<ContractItem>(`/contract-items/${id}/${action}`, { method: "POST" });
  storeItem(item);
  mock.logAudit(projectOf(item), `contract_item.${status}`, "contract_item", id, { item: item.item_code });
}

// ---------- delete ----------
/** Remove a contract, its items and (live mode) the stored document. */
export async function deleteContract(id: string): Promise<void> {
  if (LIVE) await apiFetch<void>(`/contracts/${id}`, { method: "DELETE" });
  mock.deleteContract(id);
}

/** Remove an item the AI got wrong. */
export async function deleteContractItem(id: string): Promise<void> {
  if (LIVE) await apiFetch<void>(`/contract-items/${id}`, { method: "DELETE" });
  mock.deleteContractItem(id);
}
