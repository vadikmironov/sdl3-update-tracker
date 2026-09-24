#!/usr/bin/env python3
"""Renders module/ into a Bazel registry, as BCR would hold it.

Local first: it writes a directory and does no git operation. The steps that
publish, to the `rendered` branch or into a BCR checkout, call this script.

    tools/common/render.py                       # the version of upstream.json
    tools/common/render.py --version 3.0.6 --out /tmp/old
    tools/common/render.py --check ~/devel/bazel-central-registry

The output is byte-identical to what BCR's tools/update_integrity.py writes:
the same key order in source.json, the same order of the overlay files, the
same JSON format.
"""

import argparse
import base64
import hashlib
import json
import pathlib
import shutil
import sys
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import permalinks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]

# No collision with the @VAR@ and ${VAR} forms that upstream build files use.
TOKEN_UPSTREAM = b"%{upstream_version}"
TOKEN_MODULE = b"%{module_version}"

# The render is complete, but a permalink needs a person.
EXIT_PERMALINKS = 3


def integrity(data):
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode()


def json_dump(path, data):
    # As tools/registry.py in BCR: four spaces, LF, one final newline.
    with open(path, "w", newline="\n") as f:
        json.dump(data, f, indent=4)
        f.write("\n")


class Renderer:
    def __init__(self, upstream_version, bcr_revision, verified=None, cache=None, offline=False):
        self.upstream_version = upstream_version
        self.module_version = upstream_version + (".bcr.%d" % bcr_revision if bcr_revision else "")
        # The version that the line numbers of the permalinks are correct for.
        self.verified = verified or upstream_version
        self.cache = cache
        self.offline = offline
        self.links = []

    def text(self, data, name=""):
        if TOKEN_UPSTREAM in data and b"/blob/" in data and self.cache is not None:
            try:
                text, rows = permalinks.relocate(
                    data.decode(), self.verified, self.upstream_version, self.cache / "permalinks", self.offline
                )
                self.links += [(state, name, link, note) for state, link, note in rows]
                data = text.encode()
            except UnicodeDecodeError:
                pass
        return data.replace(TOKEN_UPSTREAM, self.upstream_version.encode()).replace(
            TOKEN_MODULE, self.module_version.encode()
        )

    def copy(self, src, dst):
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(self.text(src.read_bytes(), src.name))

    def copy_tree(self, src, dst):
        for f in sorted(p for p in src.rglob("*") if p.is_file()):
            self.copy(f, dst / f.relative_to(src))


def download(url, cache, offline):
    cached = cache / hashlib.sha256(url.encode()).hexdigest()[:16] / url.rsplit("/", 1)[-1]
    if cached.exists():
        return cached.read_bytes(), True
    if offline:
        sys.exit("render: %s is not in the cache and --offline is set" % url)
    print("render: downloading %s" % url)
    with urllib.request.urlopen(url) as response:
        data = response.read()
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data, False


def render(module_dir, consumers_dir, out, upstream, cache, offline):
    name = upstream["module"]
    r = Renderer(upstream["version"], upstream.get("bcr_revision", 0), upstream.get("permalinks_verified_for"), cache, offline)

    registry = out / "registry"
    for stale in (registry, out / "consumers"):
        if stale.exists():
            shutil.rmtree(stale)
    version_dir = registry / "modules" / name / r.module_version
    version_dir.mkdir(parents=True)
    (registry / "bazel_registry.json").write_text("{}\n")

    # BCR holds MODULE.bazel two times, and its validation makes sure that the
    # two are identical. One source file makes a difference impossible.
    r.copy(module_dir / "MODULE.bazel", version_dir / "MODULE.bazel")
    r.copy(module_dir / "MODULE.bazel", version_dir / "overlay" / "MODULE.bazel")
    r.copy(module_dir / "presubmit.yml", version_dir / "presubmit.yml")
    r.copy_tree(module_dir / "overlay", version_dir / "overlay")
    if (module_dir / "patches").is_dir():
        r.copy_tree(module_dir / "patches", version_dir / "patches")
    r.copy(module_dir / "README.md", version_dir.parent / "README.md")

    # The local registry lists only the rendered version. BCR owns the true
    # metadata.json, and the publish step adds the version to that file.
    metadata = json.loads(r.text((module_dir / "metadata.json").read_bytes()))
    metadata["versions"] = [r.module_version]
    json_dump(version_dir.parent / "metadata.json", metadata)

    # source.json: the template gives the key order, as the existing file does
    # for BCR's tool.
    source = json.loads(r.text((module_dir / "source.json.in").read_bytes()))
    archive, from_cache = download(source["url"], cache, offline)
    source["integrity"] = integrity(archive)

    patch_dir = version_dir / "patches"
    patches = {p.name: integrity(p.read_bytes()) for p in sorted(patch_dir.iterdir())} if patch_dir.is_dir() else {}
    if patches:
        source["patches"] = patches
    else:
        source.pop("patches", None)

    # sorted() on path objects, not on strings: "a/x" comes before "a-b/x".
    overlay_dir = version_dir / "overlay"
    files = sorted(p.relative_to(overlay_dir) for p in overlay_dir.rglob("*") if p.is_file())
    source["overlay"] = {f.as_posix(): integrity((overlay_dir / f).read_bytes()) for f in files}
    json_dump(version_dir / "source.json", source)

    if consumers_dir.is_dir():
        r.copy_tree(consumers_dir, out / "consumers")

    return name, r.module_version, version_dir, from_cache, r.links


def check(version_dir, name, module_version, bcr):
    """Compares the rendered module with a BCR checkout. Returns the differences."""
    theirs = pathlib.Path(bcr).expanduser() / "modules" / name
    pairs = [(version_dir.parent / "README.md", theirs / "README.md")]
    ours_files = sorted(p.relative_to(version_dir) for p in version_dir.rglob("*") if p.is_file())
    their_dir = theirs / module_version
    their_files = sorted(p.relative_to(their_dir) for p in their_dir.rglob("*") if p.is_file()) if their_dir.is_dir() else []
    problems = ["only in the render: %s" % f for f in ours_files if f not in their_files]
    problems += ["only in BCR: %s" % f for f in their_files if f not in ours_files]
    pairs += [(version_dir / f, their_dir / f) for f in ours_files if f in their_files]
    for ours, other in pairs:
        if not other.exists():
            problems.append("not in BCR: %s" % other)
        elif ours.read_bytes() != other.read_bytes():
            problems.append("different: %s" % other)
    return problems


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", help="upstream version; default: upstream.json")
    parser.add_argument("--bcr-revision", type=int, help="N of .bcr.N; default: upstream.json")
    parser.add_argument("--out", default=str(ROOT / "rendered"), help="output directory; default: rendered/")
    parser.add_argument("--cache", default=str(ROOT / ".cache"), help="where downloaded archives stay")
    parser.add_argument("--offline", action="store_true", help="fail if the archive is not in the cache")
    parser.add_argument("--check", metavar="BCR_CHECKOUT", help="compare the result with this BCR checkout")
    args = parser.parse_args()

    upstream = json.loads((ROOT / "upstream.json").read_text())
    if args.version:
        upstream["version"] = args.version
    if args.bcr_revision is not None:
        upstream["bcr_revision"] = args.bcr_revision

    out = pathlib.Path(args.out).expanduser().resolve()
    try:
        name, module_version, version_dir, from_cache, links = render(
            ROOT / "module", ROOT / "consumers", out, upstream, pathlib.Path(args.cache).expanduser(), args.offline
        )
    except permalinks.Offline as e:
        sys.exit("render: %s and --offline is set" % e)
    print("render: %s@%s -> %s%s" % (name, module_version, version_dir, " (archive from the cache)" if from_cache else ""))

    # The line numbers of a permalink follow the text to the new version. Only a
    # link whose text is not there needs a person.
    counts = {}
    for state, source, link, note in links:
        counts[state] = counts.get(state, 0) + 1
        if state != "same":
            print("render: permalink %-7s %s: %s  %s" % (state, source, link.split("/blob/")[1], note))
    if links:
        print("render: permalinks: " + ", ".join("%d %s" % (n, s) for s, n in sorted(counts.items())))
    needs_a_person = any(state in permalinks.NEEDS_A_PERSON for state, _, _, _ in links)

    if args.check:
        problems = check(version_dir, name, module_version, args.check)
        for problem in problems:
            print("check: " + problem)
        if problems:
            sys.exit("check: the render is NOT identical to %s" % args.check)
        print("check: byte-identical to modules/%s/%s and README.md in %s" % (name, module_version, args.check))
    else:
        print("render: a Bazel server that is in operation keeps the old source.json; run `bazel shutdown` first")
        print("render: cd %s/consumers/default && bazel test --registry=file://%s/registry --registry=https://bcr.bazel.build @%s//..." % (out, out, name))

    if needs_a_person:
        # The output is complete and can be built. Exit code 3 means only this.
        print(
            "render: a permalink needs a person. Correct the link in module/, then run "
            "tools/common/check_permalinks.py --fix, which also does the links that only moved.",
            file=sys.stderr,
        )
        sys.exit(EXIT_PERMALINKS)


if __name__ == "__main__":
    main()
