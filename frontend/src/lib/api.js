// Thin fetch wrapper: attaches the JWT, normalises errors, and handles session expiry.
const BASE = import.meta.env.PUBLIC_API_BASE || '/api';
const KEY = 'dealflow360.session';

export function getSession() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || null;
  } catch {
    return null;
  }
}

export function setSession(data) {
  localStorage.setItem(KEY, JSON.stringify({ token: data.access_token, user: data.user }));
}

export function clearSession() {
  localStorage.removeItem(KEY);
}

export function logout() {
  clearSession();
  window.location.href = '/login';
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function describe(detail) {
  if (!detail) return 'Something went wrong';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => `${(d.loc || []).filter((p) => p !== 'body').join('.')}: ${d.msg}`).join('; ');
  }
  return JSON.stringify(detail);
}

export async function api(path, { method = 'GET', body, auth = true } = {}) {
  const headers = {};
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  const session = getSession();
  if (auth && session?.token) headers.Authorization = `Bearer ${session.token}`;
  let response;
  try {
    response = await fetch(BASE + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError('Cannot reach the server. Is the API running?', 0);
  }
  if (response.status === 401 && auth) {
    clearSession();
    if (!window.location.pathname.startsWith('/login')) window.location.href = '/login?expired=1';
    throw new ApiError('Your session has expired', 401);
  }
  if (response.status === 204) return null;
  const isJson = (response.headers.get('content-type') || '').includes('application/json');
  const data = isJson ? await response.json() : await response.text();
  if (!response.ok) throw new ApiError(describe(data?.detail ?? data), response.status);
  return data;
}

export async function download(path, filename) {
  const session = getSession();
  const response = await fetch(BASE + path, { headers: { Authorization: `Bearer ${session?.token}` } });
  if (!response.ok) throw new ApiError('Download failed', response.status);
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const ROLE_LABEL = {
  admin: 'Administrator', sales_manager: 'Sales Manager', sales_rep: 'Sales Rep', finance: 'Finance',
  customer: 'Customer',
};
export const can = {
  sell: (u) => ['admin', 'sales_manager', 'sales_rep'].includes(u?.role),
  manage: (u) => ['admin', 'sales_manager'].includes(u?.role),
  finance: (u) => ['admin', 'finance'].includes(u?.role),
  admin: (u) => u?.role === 'admin',
};
