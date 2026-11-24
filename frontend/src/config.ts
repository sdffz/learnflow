export function resolveApiBase(
  explicitBase: string | undefined,
  isDevelopment: boolean,
): string {
  const configured = explicitBase?.trim();
  if (configured) return configured.replace(/\/+$/, "");
  return isDevelopment ? "http://127.0.0.1:8000/api" : "/api";
}
