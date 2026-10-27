I want to improve the robustness / functionality of the persistent volumes in this cluster. Currently, they're all local-path.

My main goals:

- make remote storage available to smaller nodes in the cluster (like raspberry pis)
- enable data integrity (checksumming), redundancy, backups / snapshots
- provide network storage (object storage or SMB / NFS) for services outside the cluster like Time Machine and Ludusavi game save backups

On other systems in the past to accomplish the integrity / backup goals, I've use ZFS pools, but I'm not sure how that would fit in here exactly.

I'm also looking at [garage](https://garagehq.deuxfleurs.fr/) for S3-compatible object storage and bcachefs.

I'll be running a mixture of 1 or 2 SSDs and about 10 - 20 HDDs on a single node for now, though there are plans to add more disks that are accessible remotely at separate sites connected via fiber internet.
