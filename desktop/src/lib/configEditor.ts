export interface ConfigData {
  agent_name?: string;
  default_model?: string;
  swarmsync_enabled?: boolean;
  swarmsync_api_url?: string;
  session_cap?: number;
  monthly_cap?: number;
  log_level?: string;
  telegram_enabled?: boolean;
  conduit_enabled?: boolean;
  enabled_models?: string[];
  subagent_enabled?: boolean;
  subagent_coding_backend?: string;
  [key: string]: unknown;
}

type FetchLike = (input: string, init?: RequestInit) => Promise<{
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
}>;

const SECRET_FIELD = /(token|password|secret|_key|api_key|vault)/i;

export function configPatchBody(config: ConfigData): ConfigData {
  const forbidden = Object.keys(config).filter((key) => SECRET_FIELD.test(key));
  if (forbidden.length) {
    throw new Error(
      `Credentials must be stored in Auth Keys, not Config: ${forbidden.join(", ")}`,
    );
  }
  return { ...config };
}

export async function patchCatoConfig(
  base: string,
  config: ConfigData,
  fetchImpl: FetchLike = fetch,
): Promise<ConfigData> {
  const body = configPatchBody(config);
  const response = await fetchImpl(`${base}/api/config`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new Error(`Config save failed (HTTP ${response.status}): invalid response`);
  }
  const record = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  if (!response.ok || record.status !== "ok") {
    throw new Error(String(record.message ?? record.error ?? `Config save failed (HTTP ${response.status})`));
  }
  if (!record.config || typeof record.config !== "object" || Array.isArray(record.config)) {
    throw new Error("Config save response did not include the saved config");
  }
  return record.config as ConfigData;
}
