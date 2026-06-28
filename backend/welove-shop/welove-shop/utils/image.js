export function buildImageUrl(url) {
  if (!url) return ''
  if (/^https?:\/\//.test(url)) return url
  return url.startsWith('/') ? url : `/${url}`
}
