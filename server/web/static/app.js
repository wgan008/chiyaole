// Shared fetch helpers for the caregiver web pages. Every JSON API call threads the
// caregiver token as the `t` query param (matches caregiver_from_token's `alias="t"`
// convention in app/deps.py) — the page itself is reached via an unauthenticated URL the
// adult child got over WeChat, per that same module's "never types a password" model.

function apiUrl(path) {
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}t=${encodeURIComponent(window.CHIYAOLE.token)}`;
}

async function apiGet(path) {
  const resp = await fetch(apiUrl(path));
  if (!resp.ok) throw new Error(await describeError(resp));
  return resp.json();
}

async function apiPostJson(path, body) {
  const resp = await fetch(apiUrl(path), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(await describeError(resp));
  return resp.json();
}

async function apiPostForm(path, formData) {
  const resp = await fetch(apiUrl(path), { method: "POST", body: formData });
  if (!resp.ok) throw new Error(await describeError(resp));
  return resp.json();
}

async function apiDelete(path) {
  const resp = await fetch(apiUrl(path), { method: "DELETE" });
  if (!resp.ok) throw new Error(await describeError(resp));
  return resp.json();
}

async function describeError(resp) {
  try {
    const body = await resp.json();
    return body.detail || `${resp.status}`;
  } catch {
    return `${resp.status}`;
  }
}

function showMsg(el, text, kind) {
  el.textContent = text;
  el.className = `msg ${kind || ""}`;
}
