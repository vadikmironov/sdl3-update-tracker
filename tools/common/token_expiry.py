#!/usr/bin/env python3
"""Opens an issue before the token for the BCR fork expires.

GitHub gives the expiry date of a token in a header of each API response,
`github-authentication-token-expiration`. The workflow reads that header and
gives it to this script in EXPIRES, so the token itself never comes here.

    EXPIRES="2027-09-19 00:00:00 UTC" tools/common/token_expiry.py --dry-run
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

WARN_DAYS = 21


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--today", help="YYYY-MM-DD, for a test")
    args = parser.parse_args()

    raw = os.environ.get("EXPIRES", "").strip()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", repo.split("/")[0] if repo else "")
    if not raw:
        # No header: the token has no expiry date, or GitHub refused the token.
        status = os.environ.get("HTTP_STATUS", "")
        if status and status != "200":
            sys.exit("token_expiry: GitHub answered %s. The token is possibly expired or revoked." % status)
        print("token_expiry: the token has no expiry date")
        return

    expires = datetime.datetime.strptime(raw.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").date()
    today = datetime.date.fromisoformat(args.today) if args.today else datetime.datetime.now(datetime.timezone.utc).date()
    left = (expires - today).days
    print("token_expiry: the token for the BCR fork expires on %s, %d days from now" % (expires, left))
    if left > WARN_DAYS:
        return

    title = "The token for the BCR fork expires on %s" % expires
    body = (
        "@%s: `BCR_FORK_TOKEN` expires on %s. After that date the publish step cannot push a branch to the fork.\n\n"
        "Make a new fine-grained token: only the BCR fork, Contents and Workflows read and write. Then run\n\n"
        "```\ngh secret set BCR_FORK_TOKEN --env bcr-publish --repo %s\n```\n\n"
        "and close this issue." % (owner, expires, repo)
    )
    if args.dry_run or not repo:
        print("token_expiry: WOULD OPEN: %s\n%s" % (title, body))
        return
    existing = json.loads(subprocess.run(["gh", "issue", "list", "--repo", repo, "--state", "open", "--search", "BCR fork expires in:title", "--json", "title"], check=True, capture_output=True, text=True).stdout)
    if any(i["title"] == title for i in existing):
        print("token_expiry: the issue is already open")
        return
    subprocess.run(["gh", "issue", "create", "--repo", repo, "--assignee", owner, "--title", title, "--body", body], check=True)


if __name__ == "__main__":
    main()
