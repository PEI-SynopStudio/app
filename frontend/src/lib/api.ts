export async function fetchWithAuth(url: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  const secret = import.meta.env.VITE_BACKEND_AUTH_SECRET;
  if (secret) headers.set('X-Backend-Auth', secret);

  const token = localStorage.getItem('session_token');
  if (token) headers.set('Authorization', `Bearer ${token}`);
  return fetch(url, { ...options, headers });
}