#!/usr/bin/env python3
"""The canary: each check of the gate must fail when its input is bad.

A gate can pass because it stopped looking. With automerge on, no person reads
a green run, so this script does. It gives each check an input that is known to
be bad and demands a failure. It uses no network, so the result does not depend
on what upstream contains.

    tools/common/canary.py            # needs rendered/, from tools/common/render.py
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
import permalinks  # noqa: E402

failures = []


def expect(name, condition, detail=""):
    print("%-4s %s%s" % ("ok" if condition else "FAIL", name, "" if condition else "  <- " + detail))
    if not condition:
        failures.append(name)


def run(*args, **kwargs):
    return subprocess.run(list(args), capture_output=True, text=True, **kwargs)


def canary_render_check(tmp):
    """render.py --check must see one changed byte, a file too many, and a file too few."""
    upstream = json.loads((ROOT / "upstream.json").read_text())
    name = upstream["module"]
    rendered = ROOT / "rendered" / "registry" / "modules" / name
    if not rendered.is_dir():
        sys.exit("canary: run tools/common/render.py first")

    def fake_bcr(label, damage):
        bcr = tmp / label
        shutil.copytree(rendered, bcr / "modules" / name)
        version_dir = next(p for p in (bcr / "modules" / name).iterdir() if p.is_dir())
        damage(version_dir)
        return run(sys.executable, str(HERE / "render.py"), "--offline", "--out", str(tmp / "out"), "--check", str(bcr))

    expect("render --check passes on an exact copy", fake_bcr("exact", lambda d: None).returncode == 0)

    def one_byte(d):
        f = d / "overlay" / "BUILD.bazel"
        f.write_bytes(f.read_bytes() + b"\n")

    expect("render --check sees one changed byte", fake_bcr("byte", one_byte).returncode != 0)
    expect("render --check sees a file that BCR has and the render does not", fake_bcr("extra", lambda d: (d / "overlay" / "extra.bzl").write_text("x\n")).returncode != 0)
    expect("render --check sees a file that the render has and BCR does not", fake_bcr("absent", lambda d: (d / "presubmit.yml").unlink()).returncode != 0)
    expect("render --check sees a changed hash in source.json", fake_bcr("hash", lambda d: (d / "source.json").write_text((d / "source.json").read_text().replace("sha256-", "sha256-A", 1))).returncode != 0)


def canary_permalinks(tmp):
    """relocate() must tell same, moved, changed and missing apart. The cache is the fake upstream."""
    cache = tmp / "links"
    base = ["alpha", "beta", "gamma", "delta", "epsilon"]
    files = {
        "1.0": base,
        "1.1-same": base,
        "1.1-moved": ["new first line", "another"] + base,
        "1.1-changed": ["alpha", "BETA", "gamma", "delta", "epsilon"],
        "1.1-twice": ["new first line"] + base + base,
        "1.1-short": ["alpha"],
    }
    for version, lines in files.items():
        f = cache / "o" / "r" / ("v" + version) / "f.txt"
        f.parent.mkdir(parents=True)
        f.write_text("\n".join(lines) + "\n")
    link = "https://github.com/o/r/blob/v%s/f.txt#L2-L3" % permalinks.TOKEN

    def state(version):
        text, rows = permalinks.relocate(link, "1.0", version, cache, offline=True)
        return rows[0][0], text

    expect("permalinks: same text, same place -> same", state("1.1-same") == ("same", link))
    moved = state("1.1-moved")
    expect("permalinks: same text, new place -> moved, and the line numbers follow", moved[0] == "moved" and moved[1].endswith("#L4-L5"), str(moved))
    expect("permalinks: different text -> changed", state("1.1-changed")[0] == "changed")
    expect("permalinks: text that moved and is at two places -> changed, not a guess", state("1.1-twice")[0] == "changed")
    expect("permalinks: a file that is too short -> changed or missing", state("1.1-short")[0] in permalinks.NEEDS_A_PERSON)
    missing = permalinks.relocate(link.replace("f.txt", "gone.txt"), "1.0", "1.0", cache, offline=False) if os.environ.get("CANARY_NETWORK") else None
    if missing is not None:
        expect("permalinks: a file that is not there -> missing", missing[1][0][0] == "missing")
    single = "https://github.com/o/r/blob/v%s/f.txt#L4" % permalinks.TOKEN
    text, rows = permalinks.relocate(single, "1.0", "1.1-moved", cache, offline=True)
    expect("permalinks: a link to one line keeps the one-line form", rows[0][0] == "moved" and text.endswith("#L6"), text)


def canary_gate():
    """The expression of the Gate job must fail for each result that is not success."""
    code = 'import json, os, sys; sys.exit(0 if set(json.loads(os.environ["RESULTS"])) == {"success"} else 1)'
    for results, want in (
        (["success", "success"], 0),
        (["success", "failure"], 1),
        (["success", "cancelled"], 1),
        (["success", "skipped"], 1),
        ([], 1),
    ):
        got = run(sys.executable, "-c", code, env=dict(os.environ, RESULTS=json.dumps(results))).returncode
        expect("gate: %s -> %s" % (results, "pass" if want == 0 else "fail"), got == want, "exit %d" % got)
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    expect("gate: ci.yml still has this same expression", code in workflow)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        canary_render_check(tmp)
        canary_permalinks(tmp)
        canary_gate()
        module_canary = ROOT / "tools" / "module" / "canary.sh"
        if module_canary.exists():
            result = run(str(module_canary))
            print(result.stdout, end="")
            expect("the canary of the module", result.returncode == 0, result.stderr.strip()[-200:])
    if failures:
        sys.exit("canary: %d check(s) of the gate no longer fail on a bad input: %s" % (len(failures), "; ".join(failures)))
    print("canary: each check still fails on a bad input")


if __name__ == "__main__":
    main()
