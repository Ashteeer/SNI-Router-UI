// Display an interface CIDR the way the user asked: a mask covering a single
// address shows that one IP; a wider mask shows the covered range as "from – to"
// (network → broadcast). IPv6 is shown verbatim. ponytail: IPv4 bit-twiddling only.
export function cidrRange(cidr) {
  const [ip, prefixStr] = String(cidr).split('/')
  if (ip.includes(':')) return cidr // IPv6: not enough demand to expand
  const prefix = prefixStr === undefined ? 32 : Number(prefixStr)
  const p = ip.split('.').map(Number)
  if (p.length !== 4 || p.some((n) => Number.isNaN(n) || n < 0 || n > 255)) return cidr
  const int = ((p[0] << 24) >>> 0) + (p[1] << 16) + (p[2] << 8) + p[3]
  const mask = prefix <= 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0
  const net = (int & mask) >>> 0
  const bc = (net | (~mask >>> 0)) >>> 0
  const str = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join('.')
  return net === bc ? str(net) : `${str(net)} – ${str(bc)}`
}

// Is release tag `latest` newer than installed `current`? Compares numeric parts.
export function verNewer(latest, current) {
  const nums = (v) => (String(v || '').match(/\d+/g) || []).map(Number)
  const a = nums(latest), b = nums(current)
  if (!a.length) return false
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const x = a[i] || 0, y = b[i] || 0
    if (x !== y) return x > y
  }
  return false
}
