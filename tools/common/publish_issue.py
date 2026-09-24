#!/usr/bin/env python3
"""Writes the text of the issue that asks a maintainer to open the BCR pull request.

The link opens GitHub's form with the title and a short text already in it. The
text is in the URL, so it stays short; the issue itself holds the details.

Input is the environment: MODULE, VERSION, BRANCH, FORK, BCR, OWNER, and
optionally CI_RUN_ID (the gate run), STAGE_REPORT (output of stage_into_bcr.sh).
"""

import json
import os
import pathlib
import subprocess
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[2]
env = os.environ

module, version, branch = env["MODULE"], env["VERSION"], env["BRANCH"]
fork, bcr, owner = env["FORK"], env["BCR"], env["OWNER"]
repository = env.get("GITHUB_REPOSITORY", "")
upstream_version = version.split(".bcr.")[0]

upstream = json.loads((ROOT / "upstream.json").read_text())
notes = upstream.get("release_notes", "").replace("%{upstream_version}", upstream_version)

run_id = env.get("CI_RUN_ID", "")
run_url = "https://github.com/%s/actions/runs/%s" % (repository, run_id) if run_id else ""

pr_lines = []
if notes:
    pr_lines.append("Upstream release: " + notes)
if run_url:
    pr_lines.append("Tests of this version on Linux, macOS and Windows: " + run_url)
pr_lines.append("Prepared by https://github.com/%s, opened by a maintainer." % repository)

link = "https://github.com/%s/compare/main...%s:%s?%s" % (
    bcr,
    fork.split("/")[0],
    branch,
    urllib.parse.urlencode({"quick_pull": 1, "title": "%s@%s" % (module, version), "body": "\n\n".join(pr_lines)}),
)

out = [
    "@%s: `%s@%s` passed the gate. It is in the branch `%s` of `%s`." % (owner, module, version, branch, fork),
    "",
    "## [Open the BCR pull request](%s)" % link,
    "",
    "Open it from the account of a maintainer of the module. BCR counts a version",
    "bump as approved only when its author is a maintainer, and its CLA check reads",
    "the author.",
    "",
]
if notes:
    out.append("- Upstream release: " + notes)
if run_url:
    out.append("- Gate run: " + run_url)
out.append("")

if run_id and repository:
    try:
        jobs = json.loads(
            subprocess.run(
                ["gh", "api", "--paginate", "repos/%s/actions/runs/%s/jobs" % (repository, run_id), "-q", "[.jobs[] | {name, conclusion}]"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
        out += ["## Gate", "", "| Job | Result |", "| --- | --- |"]
        out += ["| %s | %s |" % (j["name"], j["conclusion"]) for j in sorted(jobs, key=lambda j: j["name"])]
        out.append("")
    except (subprocess.CalledProcessError, ValueError) as e:
        out += ["The list of the gate jobs is not available: %s" % e, ""]

report = env.get("STAGE_REPORT", "")
if report and pathlib.Path(report).exists():
    out += ["## BCR's own tools", "", "```"] + pathlib.Path(report).read_text().strip().splitlines() + ["```", ""]

out += [
    "The daily job closes this issue when BCR main contains the version.",
]
print("\n".join(out))
