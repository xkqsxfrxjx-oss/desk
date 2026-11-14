// Desk data decryption. Key = HKDF-SHA256(APP_TOKEN, salt "desk-v1", info "data") -> AES-256-GCM.
const enc = new TextEncoder(), b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
export function creds() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (h.get("t")) localStorage.setItem("desk_t", h.get("t"));
  if (h.get("d")) localStorage.setItem("desk_d", h.get("d"));
  if (h.get("t") || h.get("d")) history.replaceState(null, "", location.pathname + location.search);
  return { t: localStorage.getItem("desk_t"), d: localStorage.getItem("desk_d") };
}
let kp = null, kt = null;
async function key(token) {
  if (kp && kt === token) return kp;
  const base = await crypto.subtle.importKey("raw", enc.encode(token), "HKDF", false, ["deriveKey"]);
  kt = token; kp = crypto.subtle.deriveKey({ name: "HKDF", hash: "SHA-256", salt: enc.encode("desk-v1"), info: enc.encode("data") },
    base, { name: "AES-GCM", length: 256 }, false, ["decrypt"]);
  return kp;
}
export async function decryptEnvelope(env, token) {
  const pt = await crypto.subtle.decrypt({ name: "AES-GCM", iv: b64(env.iv) }, await key(token), b64(env.ct));
  return JSON.parse(new TextDecoder().decode(pt));
}
