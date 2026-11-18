// Build-only CDN refresh: official package bytes and SHA512 remain fixed.
const refresh = {"selector": "@deepseek-ai/dsh-experimental-inspector@0.2.1-rc.5", "canonical_url": "https://registry.npmjs.org/@deepseek-ai/dsh-experimental-inspector/-/dsh-experimental-inspector-0.2.1-rc.5.tgz", "download_url": "https://registry.npmjs.org/@deepseek-ai/dsh-experimental-inspector/-/dsh-experimental-inspector-0.2.1-rc.5.tgz?alb_verified_download=1", "integrity": "sha512-Dds795N/Y6qZ9bgPNobmofGSlHMobvRz2ORE14xu6q9TxN3bO6uGdan0p59JH/fx4RGEiHv/LGQFa/Mt4wK96g=="};
module.exports = { hooks: { afterAllResolved(lockfile) {
  const entries = Object.entries(lockfile.packages || {}).filter(([key]) => key === refresh.selector || key.startsWith(refresh.selector + '('));
  if (!entries.length) throw new Error('Official package selector missing');
  for (const [key, item] of entries) {
    if (item.resolution.integrity !== refresh.integrity) throw new Error('Official package integrity changed: ' + key);
    const old = item.resolution.tarball;
    if (old && old !== refresh.canonical_url && old !== refresh.download_url) throw new Error('Unexpected tarball origin');
    item.resolution.tarball = refresh.download_url;
  }
  return lockfile;
} } };
