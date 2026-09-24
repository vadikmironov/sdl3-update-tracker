"""Permalinks into the upstream source, and how they follow a version bump.

A comment in the overlay gives a link such as

    https://github.com/pkgconf/pkgconf/blob/pkgconf-%{upstream_version}/meson.build#L81-L100

The line numbers in module/ are correct for one version, the value of
`permalinks_verified_for` in upstream.json. For a different version the same
text can be at a different position. `relocate` finds it and writes the new
line numbers, so that the rendered module always has correct links. A tag does
not change, so the result is always the same for the same two versions.

States of a link:
    same     the lines have the same text at the two versions
    moved    the same text is at a different position, in one place only
    changed  the text is not there, or is there more than one time
    missing  the file is not there, or it has fewer lines than the link says
Only `changed` and `missing` need a person.
"""

import re
import urllib.error
import urllib.request

TOKEN = "%{upstream_version}"
LINK = re.compile(
    r"https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)/blob/(?P<ref>[^/\s#]+)/(?P<path>[^\s#)>`\"']+)"
    r"(?:#L(?P<a>\d+)(?:-L(?P<b>\d+))?)?"
)
NEEDS_A_PERSON = ("changed", "missing")


class Offline(Exception):
    pass


def fetch(owner, repo, ref, path, cache, offline=False):
    """The lines of a file at a ref, or None if it is not there."""
    cached = cache / owner / repo / ref / path
    if cached.exists():
        return cached.read_text(errors="replace").splitlines()
    if offline:
        raise Offline("%s/%s %s:%s is not in the cache" % (owner, repo, ref, path))
    url = "https://raw.githubusercontent.com/%s/%s/%s/%s" % (owner, repo, ref, path)
    try:
        with urllib.request.urlopen(url) as response:
            data = response.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_bytes(data)
    return data.decode(errors="replace").splitlines()


def locate(block, lines):
    """Each position (1-based) of `block` in `lines`. Space at the end of a line is ignored."""
    want = [line.rstrip() for line in block]
    have = [line.rstrip() for line in lines]
    n = len(want)
    return [i + 1 for i in range(len(have) - n + 1) if have[i : i + n] == want]


def relocate(text, verified, version, cache, offline=False):
    """Moves the line numbers of each tokenised link from `verified` to `version`.

    `text` still has the token in it. Returns the new text and one row for each
    link: (state, link as written, note).
    """
    rows = []

    def one(m):
        link = m.group(0)
        if TOKEN not in m["ref"]:
            return link  # A link to a fixed ref does not change with the version.
        new = fetch(m["owner"], m["repo"], m["ref"].replace(TOKEN, version), m["path"], cache, offline)
        if new is None:
            rows.append(("missing", link, "the file is not there at %s" % version))
            return link
        if not m["a"]:
            rows.append(("same", link, "no line numbers"))
            return link
        a, b = int(m["a"]), int(m["b"] or m["a"])
        if verified == version:
            if a > b or b > len(new):
                rows.append(("missing", link, "the file has %d lines" % len(new)))
            else:
                rows.append(("same", link, ""))
            return link
        old = fetch(m["owner"], m["repo"], m["ref"].replace(TOKEN, verified), m["path"], cache, offline)
        if old is None or a > b or b > len(old):
            rows.append(("missing", link, "the lines are not there at %s, the verified version" % verified))
            return link
        block = old[a - 1 : b]
        if locate(block, new[a - 1 : b]) == [1]:
            rows.append(("same", link, ""))
            return link
        places = locate(block, new)
        if len(places) != 1:
            rows.append(("changed", link, "the text of %s is at %d places in %s" % (verified, len(places), version)))
            return link
        na = places[0]
        anchor = "#L%d-L%d" % (na, na + b - a) if m["b"] else "#L%d" % na
        rows.append(("moved", link, "now " + anchor))
        return link[: m.start("a") - m.start(0) - 2] + anchor

    return LINK.sub(one, text), rows
