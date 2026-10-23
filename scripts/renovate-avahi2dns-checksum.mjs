import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

export async function updateChecksum(contents, fetchArchive = fetch) {
  const versions = [...contents.matchAll(/^ARG AVAHI2DNS_VERSION=([0-9]+\.[0-9]+\.[0-9]+)$/gm)];
  const checksums = [...contents.matchAll(/^ARG AVAHI2DNS_SHA512=([a-f0-9]{128})$/gm)];
  assert.equal(versions.length, 1, 'Expected exactly one avahi2dns version');
  assert.equal(checksums.length, 1, 'Expected exactly one avahi2dns checksum');

  const url = `https://github.com/LouisBrunner/avahi2dns/archive/refs/tags/${versions[0][1]}.tar.gz`;
  const response = await fetchArchive(url, { signal: AbortSignal.timeout(60_000) });
  assert.ok(response.ok, `Archive download failed: HTTP ${response.status}`);
  const checksum = createHash('sha512')
    .update(Buffer.from(await response.arrayBuffer()))
    .digest('hex');
  return contents.replace(checksums[0][0], `ARG AVAHI2DNS_SHA512=${checksum}`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const file = new URL('../images/avahi2dns/Containerfile', import.meta.url);
  const original = await readFile(file, 'utf8');
  const updated = await updateChecksum(original);
  if (updated !== original) {
    await writeFile(file, updated);
  }
}
