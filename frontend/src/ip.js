// Display an interface CIDR the way the user asked: a mask covering a single
// address shows that one IP; a wider mask shows the covered range as "from – to"
// (network → last). Works for both IPv4 and IPv6. ponytail: the agent already
// filters to globally-routable addresses, so this is display-only.
export function cidrRange(cidr) {
  const s = String(cidr)
  const slash = s.lastIndexOf('/')
  const ip = slash < 0 ? s : s.slice(0, slash)
  const prefixStr = slash < 0 ? undefined : s.slice(slash + 1)
  return ip.includes(':') ? v6Range(ip, prefixStr) : v4Range(ip, prefixStr)
}

function v4Range(ip, prefixStr) {
  const prefix = prefixStr === undefined ? 32 : Number(prefixStr)
  const p = ip.split('.').map(Number)
  if (p.length !== 4 || p.some((n) => Number.isNaN(n) || n < 0 || n > 255)) return ip
  const int = ((p[0] << 24) >>> 0) + (p[1] << 16) + (p[2] << 8) + p[3]
  const mask = prefix <= 0 ? 0 : (0xffffffff << (32 - prefix)) >>> 0
  const net = (int & mask) >>> 0
  const bc = (net | (~mask >>> 0)) >>> 0
  const str = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255].join('.')
  return net === bc ? str(net) : `${str(net)} – ${str(bc)}`
}

function v6Range(ip, prefixStr) {
  const n = v6ToBig(ip)
  if (n === null) return prefixStr === undefined ? ip : `${ip}/${prefixStr}`
  let prefix = prefixStr === undefined ? 128 : Number(prefixStr)
  if (Number.isNaN(prefix)) prefix = 128
  prefix = Math.max(0, Math.min(128, prefix))
  const host = prefix >= 128 ? 0n : (1n << (128n - BigInt(prefix))) - 1n
  const mask = ((1n << 128n) - 1n) ^ host
  const net = n & mask
  const last = net | host
  return net === last ? bigToV6(net) : `${bigToV6(net)} – ${bigToV6(last)}`
}

function v6ToBig(ip) {
  let head, tail
  if (ip.includes('::')) {
    const [h, t] = ip.split('::')
    if (t === undefined || ip.indexOf('::') !== ip.lastIndexOf('::')) return null
    head = h ? h.split(':') : []
    tail = t ? t.split(':') : []
  } else {
    head = ip.split(':')
    tail = []
  }
  const missing = 8 - head.length - tail.length
  if (ip.includes('::') && missing < 0) return null
  const groups = ip.includes('::')
    ? [...head, ...Array(missing).fill('0'), ...tail]
    : head
  if (groups.length !== 8) return null
  let n = 0n
  for (const g of groups) {
    if (!/^[0-9a-fA-F]{1,4}$/.test(g)) return null
    n = (n << 16n) + BigInt(parseInt(g, 16))
  }
  return n
}

function bigToV6(value) {
  let n = value
  const groups = new Array(8)
  for (let i = 7; i >= 0; i--) { groups[i] = Number(n & 0xffffn).toString(16); n >>= 16n }
  // RFC 5952: collapse the longest run of >=2 zero groups to "::"
  let best = { start: -1, len: 0 }, cur = { start: -1, len: 0 }
  for (let i = 0; i < 8; i++) {
    if (groups[i] === '0') { if (cur.start < 0) cur = { start: i, len: 1 }; else cur.len++ }
    else { if (cur.len > best.len) best = cur; cur = { start: -1, len: 0 } }
  }
  if (cur.len > best.len) best = cur
  if (best.len >= 2) {
    return groups.slice(0, best.start).join(':') + '::' + groups.slice(best.start + best.len).join(':')
  }
  return groups.join(':')
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
