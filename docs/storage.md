# Storage architecture

## Status

This document records the agreed target architecture and its known tradeoffs. It
is a design, not a record of resources already deployed.

The first implementation is intentionally centralized on `kings-canyon`. Stateful
services may stop while that node is unavailable. Disk redundancy, snapshots,
and backups protect data, but the design does not provide a highly available
storage head.

## Goals

- Provide explicit HDD capacity and SSD performance tiers, selectable independently of filesystem or block access.
- Make persistent storage available to workloads on smaller nodes, including
  ARM64 Raspberry Pi nodes.
- Detect and repair on-disk corruption where redundancy permits.
- Survive two HDD failures within each RAIDZ2 vdev.
- Provide snapshots, local recovery copies, and encrypted cloud backups.
- Provide SMB for Time Machine and private S3-compatible object storage.
- Permit practical workloads to move between nodes while leaving workloads that
  need attached hardware explicitly pinned.
- Keep foundational ZFS, NFS, SMB, and iSCSI services independent of Kubernetes.

## Service objectives

- A storage-node outage may stop stateful applications.
- Site-loss recovery point objective (RPO): up to 24 hours for protected data.
- Recovery time objective (RTO): one to two days.
- Planned migration downtime: one full day is acceptable.
- Only irreplaceable data requires an independent off-site copy. Exceptions are
  listed under [Accepted risks](#accepted-risks).

These are design targets. The selected test and spare policies do not yet prove
the RTO under every hardware failure.

## Physical platform

`kings-canyon` will be upgraded as the combined storage and primary compute node:

- 64 GiB or more of ECC RAM
- 10 GbE storage uplink
- SAS HBA in IT mode, exposing each HDD directly
- dedicated out-of-band management
- APC SMT1500RM2U UPS
- general Kubernetes workloads remain allowed, with host resources reserved for
  the storage data plane

ZFS ARC should initially be capped around 25-33% of RAM. Kubernetes system
reservations, workload requests and limits, and scrub/resilver throttling must
prevent applications from starving storage services.

Storage traffic will use the existing trusted LAN rather than a dedicated VLAN.
Host firewall rules must restrict NFS and iSCSI to explicit Kubernetes node IPs.
iSCSI, NFS, Garage RPC, Garage administration, SMB, and S3 must remain private
and reachable remotely only through the site VPN.

## ZFS topology

### HDD pool

Create one encrypted ZFS pool containing:

- one 6 x 8 TB/TiB RAIDZ2 data vdev
- one 8 x 10 TB/TiB RAIDZ2 data vdev
- one mirrored special vdev using 2 x 2 TB SK hynix Platinum P41 SSDs

ZFS distributes allocations across both RAIDZ2 vdevs. Failure beyond RAIDZ2
tolerance in either data vdev loses the pool.

The special vdev stores metadata and blocks up to 32 KiB on selected datasets
from initial deployment. It is permanent, pool-critical storage rather than a
cache. Its two-way mirror survives one SSD failure, which is intentionally a
weaker guarantee than the two-device parity of each RAIDZ2 vdev. Loss of both
P41 devices can lose the entire pool. Special-vdev capacity and utilization must
be monitored closely.

Raw drive labels need confirmation before final capacity planning. If the drive
sizes are true TiB, parity leaves about 92 TiB before filesystem overhead and
free-space reserve. If they are manufacturer decimal TB, that is about 84 TiB.
Keep at least 20% of the pool free, producing a practical ceiling of roughly
67-74 TiB depending on the actual device sizes. The expected 30-60 TiB dataset
fits, but the upper end has limited snapshot and growth headroom.

Keep one tested, powered-off CMR HDD of at least 10 TB as a cold spare.

### HDD expansion

Expansion will occur one matching-capacity CMR disk at a time using supported
OpenZFS RAIDZ expansion. Do not mix a smaller device into a larger-capacity vdev.
Cap each RAIDZ2 vdev at 12 disks. Model newly available space conservatively:
existing blocks retain their previous data-to-parity ratio until rewritten or
replaced through normal data turnover.

### SSD pool

Use the 1.92 TB Micron 7300 PRO as a single-device encrypted ZFS pool for the SSD tier:

- CloudNativePG data zvols
- Garage metadata
- Other explicitly selected latency-sensitive application datasets and zvols

This device has enterprise power-loss protection, but it has no device-level redundancy. A failure stops all workloads using the SSD tier, including databases and Garage, until restoration. Replicate protected SSD-tier snapshots to the HDD pool hourly. A future second SSD mirror member will protect against one SSD failure, but will not make the host or iSCSI target highly available.

Reserve at least 20% free capacity on this pool as well. Size SSD-tier quotas to accommodate application data, snapshots, and growth within the remaining capacity; prioritize databases and Garage metadata before admitting other workloads.

### Tier selection

| Tier | Pool | Typical placement | Initial device-failure tolerance |
| ---- | ---- | ----------------- | -------------------------------- |
| HDD | RAIDZ2 data vdevs with the mirrored P41 special vdev | Default application files, bulk data, Garage object blocks, Time Machine, and SSD recovery copies | Two HDD failures per RAIDZ2 vdev, but only one special-vdev SSD failure |
| SSD | Micron pool | Databases, Garage metadata, and explicitly selected latency-sensitive application state | No device redundancy until a mirror member is added |

These are separate allocation tiers, not automatic hot/cold data tiering. The HDD pool's P41 special vdev remains part of the HDD tier; it is neither the SSD tier nor independently provisionable application storage. Select a tier explicitly when creating a volume. Moving existing data between tiers requires a new destination volume and a validated migration.

### Boot device

Use the 1 TB Sabrent Rocket as a single boot/root device. A boot-device failure
requires rebuilding the NixOS host. This is an intentional availability
tradeoff; the existing NixOS configuration repository and recovery secrets must
be sufficient to reproduce the host.

The Samsung 850 EVO pair and Crucial SSD are not assigned a production role by
this design. Before treating a nominally 2 TB SSD as a P41 replacement, verify
that its exact addressable sector count is at least as large.

### Common ZFS policy

- Encrypt all ZFS data with native encryption.
- Use one operational encryption key across the ZFS data hierarchy.
- Seal the automatic-unlock key to the TPM.
- Escrow recovery material in encrypted Git configuration and a password
  manager. The password-manager copy must independently unlock the Git copy.
- Keep deduplication disabled.
- Enable compression with dataset-specific settings.
- Always honor synchronous writes. Never use `sync=disabled`.
- Do not add L2ARC or SLOG devices until measurements show a need. Any future
  SLOG must use mirrored devices with power-loss protection.
- Run ZFS scrubs monthly, staggered between pools and against SMART long tests.
- Use quotas and reservations to preserve at least 20% free pool capacity.

## Host-managed storage services

The existing NixOS configuration repository owns:

- pool import and TPM-backed key loading
- NFSv4 server and exports
- iSCSI target configuration
- Samba and Time Machine configuration
- ZFS snapshot, replication, scrub, and capacity policies
- UPS and drive-health integration
- host firewall policy

Core NFS, SMB, and iSCSI services run at the host layer so storage remains
recoverable without a working Kubernetes control plane.

## Kubernetes storage

Use a CSI driver capable of provisioning ZFS datasets and zvols on the NixOS
host, with `democratic-csi` as the leading candidate. The in-cluster controller
may manage the host through a dedicated SSH identity, narrowly allowlisted
privilege rules, source-network restrictions, audit logging, and SOPS-managed
credentials.

Provide these durable storage classes so tier and access protocol can be selected independently:

| Class | Tier | Backend | Typical use | Reclaim policy |
| ----- | ---- | ------- | ----------- | -------------- |
| `zfs-nfs-hdd` | HDD | Per-PVC ZFS dataset on the HDD pool over NFS | Default, portable filesystem storage and bulk application files | `Retain` |
| `zfs-nfs-ssd` | SSD | Per-PVC ZFS dataset on the SSD pool over NFS | Latency-sensitive filesystem storage | `Retain` |
| `zfs-iscsi-hdd` | HDD | Per-PVC zvol on the HDD pool over iSCSI | Capacity-oriented RWO block-backed storage | `Retain` |
| `zfs-iscsi-ssd` | SSD | Per-PVC zvol on the SSD pool over iSCSI | Databases and latency-sensitive RWO block-backed storage | `Retain` |

Exact names may change during implementation. `zfs-nfs-hdd` replaces `local-path` as the sole default StorageClass. Applications requesting SSD or iSCSI storage must set `storageClassName` explicitly. Each class must provision into a dedicated parent dataset on its designated pool, with tier-specific quotas and snapshot policies. Durable backend datasets and zvols remain after PVC deletion and require explicit administrative cleanup.

Keep `local-path` available only for explicitly selected node-bound workloads. Any disposable scratch classes must also identify their HDD or SSD tier explicitly and use `Delete`; they must not become defaults or receive important data.

Changing the default class does not migrate existing PVCs. To change a volume's tier or protocol, provision a new PVC in the destination class, copy or restore the data with application-appropriate consistency, and update the workload through Git after validation.

Cluster-only NFS exports may use `no_root_squash` to support kubelet and init
container ownership changes. They must be restricted to fixed node IPs. Any
future external-client NFS export must use root squashing. There is no current
requirement for external NFS shares.

Expose both Kubernetes CSI `VolumeSnapshot` operations and independent
host-managed snapshot schedules. The former supports Kubernetes-native restore
workflows; the latter remains usable when the cluster is unavailable.

Portable, multi-architecture workloads may schedule on either node. Workloads
that need USB radios, printers, or other attached hardware remain pinned, while
their durable state moves to network storage where practical.

## Snapshots and backups

### Local snapshots

The default important-dataset retention policy is:

- 48 hourly snapshots
- 30 daily snapshots
- 12 monthly snapshots

Use application-aware hooks or brief quiescing where practical. Other snapshots
are only crash-consistent. High-churn caches may have shorter or no retention.

Replicate protected SSD-tier snapshots to a dedicated recovery hierarchy on the HDD pool hourly, covering both CSI datasets and zvols as well as Garage metadata. Account for these copies and their retention in HDD capacity planning. This copy improves local recovery time but is not an off-site backup and shares the same host, power, and site failure domains. The local replication recovery point target is up to one hour when replication is healthy; database-native backups remain necessary for database recovery.

### Cloud backup

Use provider-neutral, client-side encrypted backups to S3-compatible cloud
object storage. Provider and budget selection are deferred.

- Restic protects general irreplaceable files, host recovery material, and the
  selected live Garage filesystem snapshot sets.
- Retain 30 daily and 12 monthly non-database cloud recovery points.
- CloudNativePG writes database-native base backups and continuous WAL archives
  directly to cloud, providing a 30-day point-in-time recovery window.
- Ludusavi/rclone clients write directly to cloud rather than relying on local
  Garage as their independent backup.
- Cloud backups are mutable. Object lock and other immutable-retention controls
  are explicitly not required.

Full representative restore drills occur annually. Automated repository checks
and smaller restore checks are still desirable, but alert delivery and the
future Prometheus stack are outside the present scope.

## SMB and Time Machine

Run Samba at the host layer with dedicated NAS accounts. Keycloak is not an SMB
identity provider; no Samba AD domain will be introduced.

Provide one shared Time Machine dataset and SMB share with a hard 4 TiB quota
for one or two Macs. The Macs can crowd one another within that shared quota.
Do not take ZFS snapshots of the Time Machine dataset; Time Machine manages its
own history. The share remains local-only and is not copied to cloud.

## Garage object storage

Deploy Garage inside Kubernetes, pinned to `kings-canyon`, with static retained
local volumes backed directly by ZFS rather than network CSI:

- Garage metadata on the Micron SSD pool
- Garage object blocks on the HDD pool

The initial service is private, uses replication factor 1, and is capped at
1 TiB across durable buckets while remote capacity is unknown. It provides
application object storage and an experimentation target; it is not the
independent backup destination for Kubernetes or Ludusavi.

Garage filesystem backups use live snapshots only. Because metadata and object
blocks are on different pools, they cannot be captured atomically. Use Garage's
live metadata snapshot support, ordered dataset snapshots, and a shared backup
manifest to reduce inconsistency risk. Restores may require Garage repair. This
is weaker than a quiesced snapshot or S3-level object copy and is an accepted
risk.

Within one to two years, add two remote storage sites connected through
symmetric gigabit fiber and a private VPN. Remote Garage nodes run directly on
their hosts, not in this Kubernetes cluster. Create a new three-zone Garage
cluster with replication factor 3, copy and verify objects from the local
factor-1 service through the S3 API, and retire the old service only after
validation. Do not change the existing cluster's replication factor in place.

Garage duplicates objects rather than using erasure coding, so each future zone
must reserve enough capacity for the full protected Garage dataset plus free
space.

## Migration outline

1. Upgrade `kings-canyon`, preserving the current local-path source disks.
2. Create the final encrypted pools and host storage services declaratively.
3. Before production migration, collect SMART/NVMe health baselines, complete
   extended device self-tests, review firmware, complete an empty-pool scrub,
   and run a sustained thermal/load check.
4. Validate only the happy-path workflows selected for this phase: dynamic NFS and iSCSI provisioning on both HDD and SSD tiers, correct destination-pool placement for each class, mounts from amd64 and ARM64 nodes, snapshots, restores, quotas, SSD-to-HDD replication and recovery, and representative application I/O.
5. Migrate and validate applications one at a time during the full-day window.
   Use database-native backup/restore or replication for PostgreSQL and
   application-aware copies where available.
6. Keep each original local-path volume offline and unchanged for 14 days. Do
   not allow source and destination to receive writes concurrently.
7. Remove old volumes only through a separate reviewed Git change after backup
   and application validation.

## Accepted risks

- `kings-canyon`, its HBA, chassis, backplane, PSU, and network path remain single
  points of service failure.
- The two-way P41 special vdev survives one SSD failure, not two; losing it loses
  the HDD pool.
- The Micron SSD tier and Sabrent boot device initially have no mirror. All SSD-tier workloads share this device-failure risk; hourly HDD replication provides recovery copies rather than automatic failover.
- The UPS batteries need replacement. Deployment may begin first, despite the
  elevated risk to consumer SSDs and synchronous writes; remediation should be
  treated as urgent.
- Hardware-spare coverage beyond the one cold HDD is out of scope.
- Pre-production validation exercises happy paths only, not simulated disk,
  special-vdev, HBA, encrypted-import, or full disaster failures.
- Full restore drills occur annually rather than quarterly.
- Mutable cloud backups do not resist deletion by compromised backup
  credentials or mistaken pruning.
- Time Machine is local-only, so a site event can remove both Macs and their
  backup history.
- Live Garage snapshots across two pools are not atomic and may require repair
  during recovery.
- A shared Time Machine quota allows one client to consume space needed by the
  other.
- Monitoring delivery, Prometheus, non-disk hardware spares, cloud-provider
  selection, and control-plane datastore backup are deferred.

## References

- [OpenZFS special vdev guidance](https://openzfs.github.io/openzfs-docs/Basic%20Concepts/Pool%20Structure/Special%20vdev.html)
- [Garage goals and non-goals](https://garagehq.deuxfleurs.fr/documentation/design/goals/)
- [Garage configuration and replication factors](https://garagehq.deuxfleurs.fr/documentation/reference-manual/configuration/)
- [Garage durability and repair](https://garagehq.deuxfleurs.fr/documentation/operations/durability-repairs/)
