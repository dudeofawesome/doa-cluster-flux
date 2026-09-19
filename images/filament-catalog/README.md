# OFD catalog adapter

This standard-library Python converter transforms the official Open Filament Database bulk release into Spoolman's external catalog format. `refresh` writes a catalog; a separate official Nginx image serves the files. The converter image runs tests during its build, supports amd64 and arm64, and runs as UID/GID 1000.

The source is `https://github.com/OpenFilamentCollective/open-filament-database/releases/latest/download/all.json.gz`. This is the same bulk export published by OFD's dataset workflow; using the release asset also avoids dependence on its custom API domain. `OFD_SOURCE_URL` can override the HTTPS URL. Downloads are limited to 32 MiB compressed and 128 MiB decompressed, with a 90-second socket timeout. The Kubernetes Job imposes an overall 15-minute deadline and retries failed executions twice.

## Mapping

The bulk export contains separate brands, materials, filaments, variants and sizes arrays. Foreign keys join these arrays, but external IDs use `ofd:<size.uuid>` from the canonical UUIDv4 field. The export's generated `id` fields are used only for joins because they can change when products are renamed. Missing canonical UUIDs, duplicate IDs, broken references, invalid colors and missing/nonpositive density, diameter or filament weight reject the entire update. Non-FFF sizes are excluded and counted. Discontinued entries remain available for existing stock.

| OFD data | Spoolman catalog field / policy |
|---|---|
| Brand name | `manufacturer` |
| Product and color names | `name`, with `(refill)` appended for refills |
| Material | `material` |
| Product density | `density`; no invented fallback |
| Size filament weight and diameter | `weight`, `diameter` |
| Empty spool weight | `spool_weight` when known; refills do not imply a zero-weight reusable spool |
| One/multiple hex colors | `color_hex` / `color_hexes`, normalized without `#` |
| Nozzle/bed temperature ranges | Midpoint rounded half up; a lone bound is used as-is; unknown temperatures are omitted |
| Matte, glow, transparent/translucent | Corresponding supported appearance fields |
| Marble / glitter | `pattern: marble` / `sparkle` |
| Coextruded / gradual color change | `multi_color_direction: coaxial` / `longitudinal` |

The generic `materials.json` contains one entry per material name, with the median density across distinct represented product lines. It supplies an approximate generic default without overweighting products with more color or spool-size variants. Filament entries retain their exact OFD densities. Generic temperatures are omitted because they depend on the product. Temperature midpoints are catalog defaults, not validated printer profiles. Unsupported OFD fields are not written to Spoolman's inventory or custom fields.

## Publication and recovery

Writers serialize using `flock` on the PVC. The bootstrap init container runs `refresh --if-missing`, verifies existing file checksums, and avoids downloading when a valid catalog exists. A new installation needs a successful first download. Corrupt existing catalogs fail visibly rather than silently losing the removal baseline.

Refreshes validate before writing a new generation directory. `CATALOG_MIN_RECORDS` defaults to 1000 and `CATALOG_MAX_DROP` defaults to 0.2: removing more than 20% of previously published external IDs is rejected even if the total record count has not fallen. Older source timestamps are rejected. Changing either guard requires a reviewed settings change in Git; a legitimate upstream UUID migration may require such a change and won't automatically relink existing inventory.

The converter writes and fsyncs complete files, then atomically replaces the `current` symlink. It retains the preceding successful generation and deletes older generations during the next successful refresh. Downloads and validation failures leave `current` untouched. Each HTTP response reads a complete file; Spoolman's separate requests for filaments and materials can straddle publication, so this does not provide a transaction across both endpoints. These files have no cross-file IDs or referential constraints.

Nginx exposes only `/filaments.json`, `/materials.json`, `/metadata.json` and `/healthz`; it does not provide directory listings or write APIs. Its configuration lives in `apps/home/spoolman/catalog-nginx.conf`, mounted through a generated ConfigMap. It runs as UID/GID 1000 with a read-only root filesystem and catalog PVC, plus a small writable `/tmp` volume for its PID and temporary files. Nginx starts directly without the image's entrypoint scripts. Responses send `Cache-Control: no-store`; file caching and conditional 304 responses are disabled so atomic symlink updates are visible immediately, including replacements within the same second. Metadata still includes source URL/version/timestamp/checksum, converted-file checksums, counts and the last successful refresh timestamp.

There is no custom metrics endpoint or catalog PodMonitor. Prometheus uses kube-state-metrics: CronJob last successful completion time drives the 48-hour refresh alert, falling back to CronJob creation time until the first successful scheduled run. The bootstrap init container does not count as a successful CronJob run. Deployment available replicas drive the availability alert, and the existing Kubernetes Job failure alert covers failed refreshes. Nginx remains healthy while serving older valid data; freshness is monitored separately.

## Validation

From the repository root:

```sh
devenv shell --quiet -- python -m unittest discover \
  -s images/filament-catalog -p 'test_*.py' -v

# Optional: download and convert the current release into a local scratch directory.
devenv shell --quiet -- python images/filament-catalog/catalog.py refresh \
  --data-dir /private/tmp/filament-catalog-check

# Or validate a previously downloaded, uncompressed bulk snapshot offline.
devenv shell --quiet -- python images/filament-catalog/catalog.py refresh \
  --input /private/tmp/ofd-all.json \
  --data-dir /private/tmp/filament-catalog-check
```

Tests cover identity stability, mapping, invalid data, deletion/rollback guards, cache integrity, concurrent bootstrap writers and generation retention. The build workflow runs them inside the converter image too. Validate Nginx separately with its deployed configuration and read-only mounts, including serving a newly published generation without restarting the server.

## Image publication

The existing `Build images` workflow builds this image on relevant pull requests and publishes it on pushes to `main`, scheduled builds and manual dispatch. The initial tag is `ghcr.io/dudeofawesome/filament-catalog:0.1.0`; bump both `CATALOG_VERSION` in the Containerfile and `VERSION` in `catalog.py` when releasing converter changes, then update the two converter image references in `apps/home/spoolman/catalog.yaml`. Publish the image and ensure the GHCR package is publicly pullable before deploying its manifests. Pin the published manifest digest in both references once available. The Nginx server uses an independently pinned official image.

References: [OFD bulk exporter](https://github.com/OpenFilamentCollective/open-filament-database/blob/main/ofd/builder/exporters/json_exporter.py), [OFD schema documentation](https://github.com/OpenFilamentCollective/open-filament-database/blob/main/docs/manual.md), [Spoolman 0.26.1 external catalog model](https://github.com/Donkie/Spoolman/blob/v0.26.1/spoolman/externaldb.py).
