"""Downloads a URL. It tries again when the failure can be temporary.

GitHub sometimes gives a 5xx for a release archive, or a connection stops. A
second attempt some seconds later usually gets the file.
"""

import http.client
import sys
import time
import urllib.error
import urllib.request

TIMEOUT = 60
# The wait before each attempt after the first.
WAITS = (10, 30)


class Error(Exception):
    """The download failed. `code` is the HTTP status, or None if there was no response."""

    def __init__(self, url, reason, code=None):
        super().__init__("cannot download %s: %s" % (url, reason))
        self.code = code


def read(url):
    for wait in (*WAITS, None):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429 or wait is None:
                raise Error(url, e, e.code) from e
            reason = e
        except (OSError, http.client.HTTPException) as e:
            if wait is None:
                raise Error(url, e) from e
            reason = e
        print("net: %s: %s; next attempt in %d s" % (url, reason, wait), file=sys.stderr)
        time.sleep(wait)
