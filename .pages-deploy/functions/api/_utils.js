const encoder = new TextEncoder();

function getCookie(request, name) {
  const cookie = request.headers.get('cookie') || '';
  const parts = cookie.split(';').map((p) => p.trim());
  const prefix = `${name}=`;
  const hit = parts.find((p) => p.startsWith(prefix));
  return hit ? decodeURIComponent(hit.slice(prefix.length)) : null;
}

function json(data, init = {}) {
  const headers = new Headers(init.headers || {});
  headers.set('content-type', 'application/json; charset=utf-8');
  headers.set('cache-control', 'no-store');
  return new Response(JSON.stringify(data), { ...init, headers });
}

function corsHeaders() {
  return {
    'access-control-allow-origin': '*',
    'access-control-allow-methods': 'GET,POST,OPTIONS',
    'access-control-allow-headers': 'content-type',
    'access-control-allow-credentials': 'true',
  };
}

function optionsResponse() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

async function sign(sessionId, secret) {
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, encoder.encode(sessionId));
  const bytes = new Uint8Array(sig);
  let raw = '';
  for (const b of bytes) raw += String.fromCharCode(b);
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

async function makeSessionToken(sessionId, secret) {
  const mac = await sign(sessionId, secret);
  return `${sessionId}.${mac}`;
}

async function isAuthed(request, env) {
  const secret = env.SESSION_SECRET || 'change-me-session-secret';
  const token = getCookie(request, 'session_id');
  if (!token || !token.includes('.')) return false;
  const idx = token.lastIndexOf('.');
  const sessionId = token.slice(0, idx);
  const sent = token.slice(idx + 1);
  const expected = await sign(sessionId, secret);
  return sent === expected;
}

export { corsHeaders, getCookie, isAuthed, json, makeSessionToken, optionsResponse };
