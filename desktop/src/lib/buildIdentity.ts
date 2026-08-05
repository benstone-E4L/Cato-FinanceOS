const FULL_SHA_PATTERN = /^[0-9a-f]{40}$/i;

function normalizeSha(value: string | undefined): string {
  const candidate = value?.trim() ?? "";
  return FULL_SHA_PATTERN.test(candidate) ? candidate.toLowerCase() : "development";
}

function normalizeVersion(value: string | undefined): string {
  const candidate = value?.trim() ?? "";
  return candidate || "development";
}

export const BUILD_IDENTITY = Object.freeze({
  version: normalizeVersion(import.meta.env.VITE_CATO_BUILD_VERSION),
  sha: normalizeSha(import.meta.env.VITE_CATO_BUILD_SHA),
});

export const BUILD_IDENTITY_LABEL = BUILD_IDENTITY.sha === "development"
  ? `${BUILD_IDENTITY.version} · local build`
  : `${BUILD_IDENTITY.version} · ${BUILD_IDENTITY.sha.slice(0, 8)}`;
