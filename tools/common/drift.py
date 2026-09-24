#!/usr/bin/env python3
"""Compares this repository with BCR, and looks after the open publish issues.

    tools/common/drift.py <BCR checkout> [--dry-run]

It opens an issue when:
  * BCR holds the current version, and it is not byte-identical to the render.
    A person changed the module in BCR directly. The next automatic bump would
    remove that change.
  * BCR holds a version that is newer than upstream.json, for example a
    `.bcr.1` fix by a co-maintainer.

For each open issue "Publish <module>@<version> to BCR": it closes the issue
when BCR holds the version, and it adds a reminder after one week.

It needs `gh` and GH_TOKEN for the issues. With --dry-run it prints what it
would do.
"""

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
REMINDER_DAYS = 7


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def version_key(v):
    """Orders 3.0.7 < 3.0.7.bcr.1 < 3.0.10. Enough for the versions of one module."""
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("bcr", help="a BCR checkout; modules/<name>/ is sufficient")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", repo.split("/")[0] if repo else "")
    upstream = json.loads((ROOT / "upstream.json").read_text())
    name = upstream["module"]
    ours = upstream["version"] + (".bcr.%d" % upstream["bcr_revision"] if upstream.get("bcr_revision") else "")
    bcr_module = pathlib.Path(args.bcr).expanduser() / "modules" / name
    theirs = json.loads((bcr_module / "metadata.json").read_text())["versions"]
    print("drift: this repository has %s@%s; BCR has %s" % (name, ours, ", ".join(theirs)))

    open_issues = json.loads(gh("issue", "list", "--repo", repo, "--state", "open", "--limit", "100", "--json", "number,title,updatedAt")) if repo else []
    titles = {i["title"] for i in open_issues}

    def open_issue(title, body):
        if title in titles:
            print("drift: an issue with this title is already open: %s" % title)
        elif args.dry_run or not repo:
            print("drift: WOULD OPEN: %s\n%s" % (title, body))
        else:
            gh("issue", "create", "--repo", repo, "--assignee", owner, "--title", title, "--body", body)
            print("drift: opened: %s" % title)

    problems = 0

    newer = [v for v in theirs if version_key(v) > version_key(ours)]
    if newer:
        problems += 1
        open_issue(
            "BCR has %s@%s, which this repository does not know" % (name, newer[-1]),
            "@%s: BCR holds %s. `upstream.json` here says %s.\n\n"
            "A person added a version to BCR directly. Bring that change into `module/` and set "
            "`upstream.json`, or the next automatic bump removes the change." % (owner, ", ".join(newer), ours),
        )

    if ours in theirs:
        result = subprocess.run(
            [sys.executable, str(HERE / "render.py"), "--out", str(ROOT / "rendered"), "--check", str(args.bcr)],
            capture_output=True,
            text=True,
        )
        differences = [line for line in result.stdout.splitlines() if line.startswith("check: ") and "byte-identical" not in line]
        if "byte-identical" in result.stdout:
            print("drift: the render of %s is byte-identical to BCR" % ours)
        else:
            problems += 1
            open_issue(
                "BCR and this repository are different for %s@%s" % (name, ours),
                "@%s: the render of `module/` is not byte-identical to BCR main.\n\n```\n%s\n```\n\n"
                "A BCR version does not change after the merge, so examine which side is wrong. "
                "`tools/common/render.py --check <BCR checkout>` shows this locally."
                % (owner, "\n".join(differences) or result.stdout[-1500:] + result.stderr[-500:]),
            )
    else:
        print("drift: BCR does not have %s yet; there is nothing to compare" % ours)

    now = datetime.datetime.now(datetime.timezone.utc)
    for issue in open_issues:
        m = re.fullmatch(r"Publish %s@(\S+) to BCR" % re.escape(name), issue["title"])
        if not m:
            continue
        version, number = m.group(1), str(issue["number"])
        age = (now - datetime.datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))).days
        if version in theirs:
            action = "close #%s: BCR has %s@%s" % (number, name, version)
            if not args.dry_run:
                gh("issue", "close", number, "--repo", repo, "--comment", "BCR main contains %s@%s." % (name, version))
        elif age >= REMINDER_DAYS:
            action = "remind on #%s: %d days with no change" % (number, age)
            if not args.dry_run:
                gh("issue", "comment", number, "--repo", repo, "--body", "@%s: %s@%s still waits for its BCR pull request." % (owner, name, version))
        else:
            action = "leave #%s open: %d days" % (number, age)
        print("drift: %s%s" % ("WOULD " if args.dry_run else "", action))

    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
