#!/usr/bin/env python3
"""Shows the state of each permalink, and writes new line numbers into module/.

The renderer already moves the line numbers when it renders a different
version; see permalinks.py. This script is for a person, when the renderer
reports a link that it cannot move.

    check_permalinks.py                   # the state of each link at the version of upstream.json
    check_permalinks.py --version 3.0.8   # the same, for a different version
    check_permalinks.py --version 3.0.8 --fix

`--fix` writes the new line numbers of each `moved` link into module/. It sets
`permalinks_verified_for` only when no link stays `changed` or `missing`:
correct those links by hand, then run `--fix` again.
"""

import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import permalinks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", help="the version to examine; default: upstream.json")
    parser.add_argument("--fix", action="store_true", help="write the new line numbers into module/")
    parser.add_argument("--cache", default=str(ROOT / ".cache" / "permalinks"))
    args = parser.parse_args()

    upstream_path = ROOT / "upstream.json"
    upstream = json.loads(upstream_path.read_text())
    version = args.version or upstream["version"]
    verified = upstream.get("permalinks_verified_for", upstream["version"])
    cache = pathlib.Path(args.cache).expanduser()

    counts, new_texts = {}, {}
    for source in sorted(p for p in (ROOT / "module").rglob("*") if p.is_file()):
        try:
            text = source.read_text()
        except UnicodeDecodeError:
            continue
        if permalinks.TOKEN not in text:
            continue
        new_text, rows = permalinks.relocate(text, verified, version, cache)
        for state, link, note in rows:
            counts[state] = counts.get(state, 0) + 1
            if state != "same":
                print("%-8s %s: %s  %s" % (state, source.relative_to(ROOT), link.split("/blob/")[1], note))
        if new_text != text:
            new_texts[source] = new_text

    summary = ", ".join("%d %s" % (n, s) for s, n in sorted(counts.items())) or "no links"
    print("check_permalinks: line numbers verified for %s, examined at %s: %s" % (verified, version, summary))
    needs_a_person = any(counts.get(s) for s in permalinks.NEEDS_A_PERSON)

    if args.fix:
        for source, text in new_texts.items():
            source.write_text(text)
            print("check_permalinks: wrote new line numbers into %s" % source.relative_to(ROOT))
        if needs_a_person:
            sys.exit("check_permalinks: correct the links above by hand in module/, then run --fix again")
        if verified != version:
            upstream["permalinks_verified_for"] = version
            upstream_path.write_text(json.dumps(upstream, indent=4) + "\n")
            print("check_permalinks: permalinks_verified_for is now %s" % version)
        return
    if needs_a_person:
        sys.exit(1)


if __name__ == "__main__":
    main()
