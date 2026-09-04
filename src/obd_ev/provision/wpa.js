// PBKDF2-HMAC-SHA1, enough of it to derive a WPA2 PMK in the browser.
//
// Why not crypto.subtle: the setup page is served over plain HTTP from the
// Pi's own access point, which is not a "secure context", so the WebCrypto
// API is unavailable. Deriving here rather than on the Pi is the whole point
// of the design -- the passphrase must never leave this page.

function utf8(str) { return new TextEncoder().encode(str); }

function sha1(msg) {
  const ml = msg.length;
  const buf = new Uint8Array((((ml + 8) >> 6) + 1) << 6);
  buf.set(msg);
  buf[ml] = 0x80;
  const dv = new DataView(buf.buffer);
  const bits = ml * 8;
  dv.setUint32(buf.length - 8, Math.floor(bits / 4294967296), false);
  dv.setUint32(buf.length - 4, bits >>> 0, false);

  let h0 = 0x67452301, h1 = 0xEFCDAB89, h2 = 0x98BADCFE,
      h3 = 0x10325476, h4 = 0xC3D2E1F0;
  const w = new Int32Array(80);

  for (let i = 0; i < buf.length; i += 64) {
    for (let j = 0; j < 16; j++) w[j] = dv.getInt32(i + j * 4, false);
    for (let j = 16; j < 80; j++) {
      const n = w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16];
      w[j] = (n << 1) | (n >>> 31);
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4;
    for (let j = 0; j < 80; j++) {
      let f, k;
      if (j < 20)      { f = (b & c) | (~b & d);            k = 0x5A827999; }
      else if (j < 40) { f = b ^ c ^ d;                     k = 0x6ED9EBA1; }
      else if (j < 60) { f = (b & c) | (b & d) | (c & d);   k = 0x8F1BBCDC; }
      else             { f = b ^ c ^ d;                     k = 0xCA62C1D6; }
      const t = (((a << 5) | (a >>> 27)) + f + e + k + w[j]) | 0;
      e = d; d = c; c = (b << 30) | (b >>> 2); b = a; a = t;
    }
    h0 = (h0 + a) | 0; h1 = (h1 + b) | 0; h2 = (h2 + c) | 0;
    h3 = (h3 + d) | 0; h4 = (h4 + e) | 0;
  }
  const out = new Uint8Array(20);
  const odv = new DataView(out.buffer);
  odv.setInt32(0, h0, false); odv.setInt32(4, h1, false);
  odv.setInt32(8, h2, false); odv.setInt32(12, h3, false);
  odv.setInt32(16, h4, false);
  return out;
}

function hmacSha1(key, msg) {
  let k = key.length > 64 ? sha1(key) : key;
  const ipad = new Uint8Array(64), opad = new Uint8Array(64);
  for (let i = 0; i < 64; i++) {
    const b = i < k.length ? k[i] : 0;
    ipad[i] = b ^ 0x36;
    opad[i] = b ^ 0x5c;
  }
  const inner = new Uint8Array(64 + msg.length);
  inner.set(ipad); inner.set(msg, 64);
  const outer = new Uint8Array(84);
  outer.set(opad); outer.set(sha1(inner), 64);
  return sha1(outer);
}

function pbkdf2Sha1(pass, salt, iterations, dkLen) {
  const out = new Uint8Array(dkLen);
  let offset = 0, block = 1;
  while (offset < dkLen) {
    const seed = new Uint8Array(salt.length + 4);
    seed.set(salt);
    new DataView(seed.buffer).setUint32(salt.length, block, false);
    let u = hmacSha1(pass, seed);
    const t = new Uint8Array(u);
    for (let i = 1; i < iterations; i++) {
      u = hmacSha1(pass, u);
      for (let j = 0; j < 20; j++) t[j] ^= u[j];
    }
    const n = Math.min(20, dkLen - offset);
    out.set(t.subarray(0, n), offset);
    offset += n;
    block++;
  }
  return out;
}

// IEEE 802.11i: PMK = PBKDF2(passphrase, ssid, 4096, 256 bits).
// NetworkManager accepts the 64-hex PMK anywhere it accepts a passphrase.
function wpaPsk(ssid, passphrase) {
  const pmk = pbkdf2Sha1(utf8(passphrase), utf8(ssid), 4096, 32);
  return Array.from(pmk, b => b.toString(16).padStart(2, "0")).join("");
}
