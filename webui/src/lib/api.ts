function syncTokenCookie(token: string): void {
  if (typeof document === 'undefined') return;
  if (token) {
    document.cookie = `exif_tagger_token=${encodeURIComponent(token)}; path=/; SameSite=Strict`;
  } else {
    document.cookie = 'exif_tagger_token=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Strict';
  }
}

export function getApiToken(): string {
  return typeof localStorage !== 'undefined' ? localStorage.getItem('exif_tagger_api_token') || '' : '';
}

export function setApiToken(token: string): void {
  const trimmed = token.trim();
  localStorage.setItem('exif_tagger_api_token', trimmed);
  syncTokenCookie(trimmed);
}

// Synchronize cookie on load if token is already in localStorage
if (typeof window !== 'undefined') {
  const existingToken = getApiToken();
  if (existingToken) {
    syncTokenCookie(existingToken);
  }
}

export function getImageUrl(url: string): string {
  const token = getApiToken();
  if (!token) return url;
  const separator = url.includes('?') ? '&' : '?';
  return `${url}${separator}token=${encodeURIComponent(token)}`;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers || {});
  const token = getApiToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const resp = await fetch(path, { ...init, headers });
  if (resp.status === 401) {
    window.dispatchEvent(new CustomEvent('api-unauthorized'));
  }
  return resp;
}
