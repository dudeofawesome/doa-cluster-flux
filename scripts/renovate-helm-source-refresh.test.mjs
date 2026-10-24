import assert from 'node:assert/strict';
import { test } from 'node:test';
import { refreshSource } from './renovate-helm-source-refresh.mjs';

const source = `apiVersion: source.toolkit.fluxcd.io/v1
kind: HelmRepository
metadata:
  name: jetstack
  namespace: flux-system
spec:
  interval: 1h
  url: https://charts.jetstack.io
`;
const upgrade = {
  manager: 'flux', datasource: 'helm', depName: 'cert-manager',
  registryUrls: ['https://charts.jetstack.io/'],
  currentValue: 'v1.21.2', newValue: 'v1.21.3',
};

test('refreshes only the matching HTTP source for a Helm chart update', () => {
  const updated = refreshSource(source, [upgrade]);
  assert.match(updated, /    reconcile\.fluxcd\.io\/requestedAt: renovate-[a-f0-9]{64}\n/);
  assert.equal(updated.replace(/  annotations:\n    reconcile\.fluxcd\.io\/requestedAt:.*\n/, ''), source);
  assert.equal(refreshSource(source.replace('charts.jetstack.io', 'other.example'), [upgrade]), source.replace('charts.jetstack.io', 'other.example'));
  assert.equal(refreshSource(source, [{ ...upgrade, datasource: 'docker' }]), source);
  assert.equal(refreshSource(source, [{ ...upgrade, registryUrls: undefined }]), source);
  const oci = source.replace('spec:\n', 'spec:\n  type: oci\n');
  assert.equal(refreshSource(oci, [upgrade]), oci);
});

test('preserves existing metadata and annotations, replacing the refresh token', () => {
  const annotated = source.replace('  name: jetstack', '  annotations:\n    example.com/keep: yes\n    reconcile.fluxcd.io/requestedAt: old\n  name: jetstack');
  const updated = refreshSource(annotated, [upgrade]);
  assert.match(updated, /    example.com\/keep: yes\n/);
  assert.equal((updated.match(/reconcile\.fluxcd\.io\/requestedAt/g) ?? []).length, 1);
  assert.equal(refreshSource(updated, [upgrade]), updated);
  assert.notEqual(refreshSource(updated, [{ ...upgrade, newValue: 'v1.21.4' }]), updated);
  const noToken = annotated.replace('    reconcile.fluxcd.io/requestedAt: old\n', '');
  const inserted = refreshSource(noToken, [upgrade]);
  assert.equal(inserted.match(/    reconcile\.fluxcd\.io\/requestedAt:.*\n/)[0], updated.match(/    reconcile\.fluxcd\.io\/requestedAt:.*\n/)[0]);
  assert.equal(inserted.replace(/    reconcile\.fluxcd\.io\/requestedAt:.*\n/, ''), noToken);
});

test('grouped updates are deterministic regardless of order or duplicates', () => {
  const other = { ...upgrade, depName: 'another-chart', newValue: '2.0.0' };
  assert.equal(refreshSource(source, [upgrade, other]), refreshSource(source, [other, upgrade, upgrade]));
  assert.notEqual(refreshSource(source, [upgrade]), refreshSource(source, [upgrade, other]));
});
