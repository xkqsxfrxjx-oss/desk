// Decrypt desk data. Key = HKDF-SHA256(APP_TOKEN from #t=, salt "desk-v1", info "data").
const enc = new TextEncoder(), b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
export function appToken() {
  const m = location.hash.match(/[#&]t=([^&]+)/);
  if (m) { localStorage.setItem("desk_t", decodeURIComponent(m[1])); history.replaceState(null, "", location.pathname); }
  return localStorage.getItem("desk_t");
}
async function key(token) {
  const base = await crypto.subtle.importKey("raw", enc.encode(token), "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: enc.encode("desk-v1"), info: enc.encode("data") },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
}
export async function decryptEnvelope(env, token) {
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, await key(token), b64(env.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
