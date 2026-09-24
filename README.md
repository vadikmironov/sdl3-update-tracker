# sdl3-update-tracker

This repository is the source of the
[`sdl3`](https://registry.bazel.build/modules/sdl3) module in the Bazel
Central Registry (BCR). It finds new releases of
[SDL 3](https://github.com/libsdl-org/SDL), tests them, and prepares the update
for BCR.

## How it operates

1. Renovate finds a new upstream release and changes one line in
   `upstream.json`. No other file contains the version. It waits three days
   after a release, because a release can be withdrawn and a BCR version is
   permanent.
2. `tools/common/render.py` writes the module as BCR holds it: it puts the
   version in, downloads the release archive, calculates each hash, and moves
   the line numbers of the permalinks to where the same text now is.
3. CI tests the rendered module on Linux, macOS and Windows, and compares the
   Linux build config that the module generates with the output of SDL's own
   CMake configure. A patch release that passes merges with no person. A
   minor or a major release always needs a person.
4. After a green run on main, `publish.yml` stages the version into a BCR
   checkout, lets BCR's own tools examine it, and pushes a branch to a fork of
   BCR. It opens an issue here with a link that opens the BCR pull request. A
   maintainer of the module opens it: BCR counts a version bump as approved
   only when its author is a maintainer.
5. `drift.yml` closes that issue when BCR has the version. Each day it also
   makes sure that BCR and this repository are still the same.

The branch [`rendered`](../../tree/rendered) holds the current version as BCR
holds it, with links that operate. It is a copy only.

## When a job is red

| Job | It means | What to do |
| --- | --- | --- |
| Render and canary, the render step | The release archive is not there, or the patch does not apply | Look at the upstream release. A release can be withdrawn. The patch is upstream commit 32c19b9dc; when a release contains it, delete `module/patches/` and the `patch_strip` and `patches` entries in `module/source.json.in` |
| Render and canary, the canary step | A check of the gate passes for an input that is bad | Correct the check. Do not merge a version bump until this is green |
| A platform job, the module step | The new version does not build, or a test fails, on that platform and Bazel version | Read the log. Correct `module/overlay/` in the same pull request. When `testsymbols` fails to link, upstream added a source directory: add it to the globs in `module/overlay/BUILD.bazel` |
| A platform job, the test module step | A consumer cannot link the module: visibility, the archives, or on macOS the Objective-C half and its frameworks | Correct `module/overlay/BUILD.bazel` |
| A macOS consumer job | The module builds with `apple_support`, but not with `rules_cc` alone or with `toolchains_llvm` | Correct the macOS part of `module/overlay/BUILD.bazel` |
| CMake oracle | The build config that the module generates on Linux is different from what SDL's configure produces: upstream added, removed or changed a check | Download the artifact `build-config-<image>` and compare the two headers. Write the check in `module/overlay/sdl3_config_checks.bzl`. With docker, `tools/module/gen_linux_build_config.sh` makes the oracle locally |
| Permalinks | The text under a permalink changed upstream, so the renderer cannot move the link | Look at what changed: it can mean work for the overlay. Correct the link in `module/`, then run `tools/common/check_permalinks.py --version <new> --fix` |
| Gate | A job above is red | This is the one required check. `rerun.yml` starts the failed jobs again one time, on a different runner, so a red Gate means that the job failed two times |
| Publish | BCR's `update_integrity` or `bcr_validation` does not agree with the render | It is an error of this repository. `tools/common/stage_into_bcr.sh <BCR checkout>` shows it locally |
| Drift | BCR has a version that this repository does not know, or the two are not byte-identical | A person changed the module in BCR directly. Bring the change into `module/` before the next bump |
| Token expiry | GitHub refused the token for the BCR fork: it is expired or revoked. Three weeks before the date, this job opens an issue | Make a new fine-grained token for the fork only, then `gh secret set BCR_FORK_TOKEN --env bcr-publish` |

A change to `upstream.json` only needs no review. Each other path has a code
owner, so a pull request that changes a script, the module or a workflow needs
an approval.

## Local use

```shell
tools/common/render.py
cd rendered/consumers/default
bazel test --registry=file://$PWD/../../registry --registry=https://bcr.bazel.build @sdl3//...
```

Run `bazel shutdown` after each new render. A Bazel server that is in operation
keeps the old `source.json`.

To examine a different release, render it into a different directory. The
working tree does not change:

```shell
tools/common/render.py --version 3.4.14 --out /tmp/sdl3-3.4.14
diff -r /tmp/sdl3-3.4.14/registry rendered/registry
```

To make sure that the render is the same as BCR, give it a BCR checkout:

```shell
tools/common/render.py --check ~/bazel-central-registry
```

To compare the generated Linux build config with SDL's own configure, as the
CMake oracle job does:

```shell
tools/module/gen_linux_build_config.sh 3.4.16 ubuntu:24.04 > /tmp/oracle.h
cd rendered/consumers/default
bazel build --registry=file://$PWD/../../registry --registry=https://bcr.bazel.build @sdl3//:config_h
tools/module/diff_config.sh "$(bazel cquery --output=files @sdl3//:config_h)" /tmp/oracle.h
```

## Layout

| Path | Content |
| --- | --- |
| `upstream.json` | The upstream version, the number of a BCR-only revision, and the version that the line numbers of the permalinks are correct for |
| `module/` | The module. `%{upstream_version}` and `%{module_version}` replace the version |
| `module/source.json.in` | The URL and the key order of `source.json`. The renderer calculates the hashes |
| `consumers/` | Root modules that use the rendered registry: the default one with `apple_support`, one with `rules_cc` only, one on `toolchains_llvm` |
| `tools/common/` | Tools that are the same for each tracker: the renderer, the permalinks, the canary, the staging and the drift |
| `tools/module/` | Tools that are specific to sdl3: the CMake oracle and its comparison |
| `rendered/` | The output of the renderer. Git ignores it |

`module/MODULE.bazel` is one file. BCR holds it two times, and the renderer
writes the two copies, so they cannot be different.

## License

Apache-2.0, as BCR. SDL 3 is under the zlib license, and so is the one patch in
`module/patches/`, which is SDL code.
