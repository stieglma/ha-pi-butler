# Docker build follow-up

## Changes implemented

Dependency hardening runs before application metadata, rootfs, and source are
copied. The filesystem-wide SUID/SGID scan and recursive permissions on
dependencies can remain cached for source-only changes. Late permission steps
touch only the new manifest, launcher scripts, and source.

The add-on release version remains in `pi_butler/config.yaml`. The private npm
project has no release version; the non-packaged Python dependency project uses
a fixed `0.0.0`. Neither should change for application releases. The existing
default extension list moved to `pi_butler/bundled-packages.json`; profile setup,
metadata checks, and container smoke checks now read that file. Editing defaults
no longer invalidates npm installation, unless installed dependencies also change.

The dependency build now uses independent Node, Python and CLI stages derived
from a common pinned runtime base. Only installed artifacts enter the final
image; compilers and uv stay in build stages. The final stage checks native
node-pty loading and CLI execution before hardening.

Storage accounting now runs in a separate maintenance worker, reporting byte
counts through a pipe to PID 1. It retains only DAC override capability to count
private service storage; Pi's retention worker remains unprivileged. PID 1 keeps
monitoring children and handling shutdown while the scan runs. Settings catalog
labels now load concurrently with the state/entity snapshot; action snapshots
remain fresh.

## Remaining validation

The amd64 image builds under Colima/Buildx. CLI/runtime checks, all 68 container
Python tests and all five bundled plugin checks pass. Native node-pty loading is
also asserted in the final runtime stage. The container smoke test covers
unprivileged boundaries, private-storage accounting, normal shutdown and storage
limit shutdown without deleting work. Verify responsiveness with a large
workspace on the target installation.

## Deferred or skipped

- Cache measurements and Supervisor cache-retention checks: deferred.
- CI Buildx/cache import and export: skipped by user preference.
- npm/uv download cache mounts: deferred; installation still uses npm cache
  cleanup and uv `--no-cache`.
