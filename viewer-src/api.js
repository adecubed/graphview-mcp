// The token arrives in the URL fragment, which the browser never sends anywhere.
const fragment = new URLSearchParams(location.hash.slice(1));
const token = fragment.get('token') || '';

/** What open_viewer asked for: a node id to fly to, or a search to run. */
export const request = { focus: fragment.get('focus'), query: fragment.get('q') };

/** Fetch a file from the API (the token goes in a header, so a plain link would not do) and save it. */
export async function download(path, params, filename) {
  const response = await fetch(`/api/${path}?${new URLSearchParams(params)}`, {
    headers: { 'X-Graphview-Token': token },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const url = URL.createObjectURL(await response.blob());
  const link = Object.assign(document.createElement('a'), { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export async function api(path, params = {}) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    for (const item of [].concat(value)) query.append(key, item);
  }
  const response = await fetch(`/api/${path}?${query}`, {
    headers: { 'X-Graphview-Token': token },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`);
  return body;
}
