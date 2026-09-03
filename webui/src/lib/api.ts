export function getApiToken(): string {
  return localStorage.getItem('exif_tagger_api_token') || '';
}

export function setApiToken(token: string): void {
  localStorage.setItem('exif_tagger_api_token', token);
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
