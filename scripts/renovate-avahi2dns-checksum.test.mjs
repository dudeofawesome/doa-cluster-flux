import assert from 'node:assert/strict';
import { test } from 'node:test';
import { updateChecksum } from './renovate-avahi2dns-checksum.mjs';

const version = '0.2.1';
const checksum = 'ddaf35a193617abacc417349ae20413112e6fa4e89a97ea20a9eeee64b55d39a2192992a274fc1a836ba3c23a3feebbd454d4423643ce80e2a9ac94fa54ca49f';
const original = `ARG AVAHI2DNS_VERSION=${version}\nARG AVAHI2DNS_SHA512=${'0'.repeat(128)}\n`;

test('updates only the checksum for the pinned release and is idempotent', async () => {
  const fetchArchive = async (url) => {
    assert.equal(url, `https://github.com/LouisBrunner/avahi2dns/archive/refs/tags/${version}.tar.gz`);
    return new Response('abc');
  };
  const expected = original.replace('0'.repeat(128), checksum);
  assert.equal(await updateChecksum(original, fetchArchive), expected);
  assert.equal(await updateChecksum(expected, fetchArchive), expected);
});

test('fails on download errors rather than returning a new checksum', async () => {
  await assert.rejects(
    updateChecksum(original, async () => new Response('Not found', { status: 404 })),
    /Archive download failed: HTTP 404/,
  );
});

test('rejects missing, malformed, or duplicate pins before downloading', async () => {
  for (const contents of [
    original.replace(`AVAHI2DNS_VERSION=${version}`, 'AVAHI2DNS_VERSION=../../other'),
    original.replace('0'.repeat(128), 'invalid-checksum'),
    original + `ARG AVAHI2DNS_VERSION=${version}\n`,
    original + `ARG AVAHI2DNS_SHA512=${checksum}\n`,
  ]) {
    await assert.rejects(updateChecksum(contents, async () => {
      assert.fail('Malformed pins must not cause a download');
    }), /Expected exactly one avahi2dns (version|checksum)/);
  }
});
