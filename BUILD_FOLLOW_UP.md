# Docker build follow-up

## Changes implemented

Dependency cleanup now runs before application metadata, rootfs, and source are
copied. Compiler removal, the filesystem-wide SUID/SGID scan, and recursive
permissions on dependencies can remain cached for source-only changes. Late
permission steps touch only the new manifest, launcher scripts, and source.

The add-on release version remains in `pi_butler/config.yaml`. The private npm
project has no release version; the non-packaged Python dependency project uses
a fixed `0.0.0`. Neither should change for application releases. The existing
default extension list moved to `pi_butler/bundled-packages.json`; profile setup,
metadata checks, and container smoke checks now read that file. Editing defaults
no longer invalidates npm installation, unless installed dependencies also change.

These changes preserve the single-stage build. They improve reuse when the
builder retains its cache; they do not configure Supervisor cache retention.

## 1. Measure cache reuse on the actual builder

Build once, then repeat unchanged. Rebuild after each of these independent edits
and inspect the build log and elapsed time:

| Edit | Expected work |
| --- | --- |
| Python or web source | Source copy and source permissions |
| Rootfs launcher | Rootfs permissions and subsequent application layers |
| Bundled defaults | Manifest copy/permissions and subsequent application layers |
| Add-on version in config.yaml | No dependency layers invalidated |
| npm manifest/lock | npm installation and subsequent layers |
| Python manifest/lock | Python installation and subsequent layers |

Use `docker build --platform linux/amd64 -t pi-butler:test pi_butler` locally.
With BuildKit, add `--progress=plain` to inspect cache hits. Confirm equivalent
reuse under the target HA Supervisor and determine whether it retains cache and
builds without a no-cache setting. Do not assume BuildKit-only features work on
the target before checking. Record cold/warm timings and image size.

Run the existing CI image checks, native node-pty assertion, bundled plugin smoke
check, and `pi_butler/tests/container_smoke.sh` after Dockerfile changes.

## 2. Split independent dependency stages

Create a common base with runtime OS packages and identities. Derive separate
stages for Node dependencies with compilers, Python dependencies with uv, and
verified gh/glab downloads. Assemble the runtime from the common base and copy
only installed artifacts, then harden it before copying application files.

Use the same pinned Node/Debian base for the native Node builder and runtime.
Keep the Python environment at `/opt/venv` in both stages, with the same system
Python available. Preserve CLI checksums, SDK/native-module assertions, identity
setup, and permission boundaries. Validate that runtime libraries needed by
native modules remain installed.

This prevents Node changes from repeating CLI downloads/Python installation and
keeps compiler bytes out of the final image. The current late purge removes
compilers from the final filesystem but cannot remove bytes in earlier layers.

## 3. Persist CI build cache

The image job in `.github/workflows/check.yaml` currently runs a plain Docker
build on a fresh hosted runner. Add Buildx and explicit GitHub Actions cache
import/export. Load the built image into Docker so the existing `docker run`
and smoke checks continue working. Verify a subsequent workflow restores the
cache, including dependency stages (use an export mode that includes them).
This is separate from Supervisor's local cache.

## 4. Consider package-manager cache mounts

After confirming BuildKit support, mount npm and uv cache directories for their
installation steps. Remove `npm cache clean` and uv's `--no-cache` for those
mounts. Download caches should remain outside image layers. Test a dependency
change to confirm reuse; unchanged dependency layers already skip installation.

## 5. Runtime refactoring

- Move the synchronous full `/data` storage walk out of PID 1 into maintenance.
  Report usage back to the supervisor while preserving storage-limit shutdown
  behavior. Verify child monitoring and termination remain responsive with a
  large workspace, and preserve unprivileged access boundaries.
- Fetch labels concurrently with the state/entity snapshot for the settings
  catalog. Keep action authorization based on fresh state and registry data.

References: [Docker cache optimization](https://docs.docker.com/build/cache/optimize/)
and [multi-stage builds](https://docs.docker.com/build/building/multi-stage/).
