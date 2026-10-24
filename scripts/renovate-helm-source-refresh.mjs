import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile, readdir, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const annotation = 'reconcile.fluxcd.io/requestedAt';
const normalizeUrl = (url) => url.replace(/\/+$/, '');

export function refreshSource(contents, upgrades) {
  // Source manifests use one resource per file and block-style metadata/spec.
  if (!/^kind: HelmRepository\s*$/m.test(contents) || /^  type: oci\s*$/m.test(contents)) {
    return contents;
  }
  const url = contents.match(/^  url: ['"]?(https?:\/\/[^\s'"]+)['"]?\s*$/m)?.[1];
  if (!url) return contents;
  const updates = upgrades.filter((upgrade) =>
    upgrade.manager === 'flux' && upgrade.datasource === 'helm' &&
    upgrade.registryUrls?.some((registry) => normalizeUrl(registry) === normalizeUrl(url)),
  );
  if (!updates.length) return contents;

  // Stable across reruns and grouped-update ordering; no timestamp churn.
  const pins = [...new Set(updates.map(({ depName, currentValue, newValue, newDigest }) =>
    JSON.stringify([depName, currentValue, newValue, newDigest]),
  ))].sort();
  const token = `renovate-${createHash('sha256').update(JSON.stringify(pins)).digest('hex')}`;
  const metadata = contents.match(/^metadata:\n((?:[ \t].*\n)*)/m);
  assert.ok(metadata, 'Expected block-style metadata in HelmRepository');
  let block = metadata[0];
  const existing = /^    reconcile\.fluxcd\.io\/requestedAt:.*$/m;
  if (existing.test(block)) {
    block = block.replace(existing, `    ${annotation}: ${token}`);
  } else if (/^  annotations:\n/m.test(block)) {
    block = block.replace(/^  annotations:\n/m, `  annotations:\n    ${annotation}: ${token}\n`);
  } else {
    assert.ok(!/^  annotations:/m.test(block), 'Expected block-style annotations');
    block += `  annotations:\n    ${annotation}: ${token}\n`;
  }
  return contents.replace(metadata[0], block);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const dataFile = process.env.RENOVATE_POST_UPGRADE_COMMAND_DATA_FILE;
  assert.ok(dataFile, 'Missing Renovate post-upgrade data file');
  const upgrades = JSON.parse(await readFile(dataFile, 'utf8'));
  assert.ok(Array.isArray(upgrades), 'Expected an array of Renovate upgrades');
  const sources = new URL('../sources/', import.meta.url);
  for (const name of await readdir(sources)) {
    if (!name.endsWith('.yaml')) continue;
    const file = new URL(name, sources);
    const original = await readFile(file, 'utf8');
    const updated = refreshSource(original, upgrades);
    if (updated !== original) await writeFile(file, updated);
  }
}
