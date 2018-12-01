# -*- coding: utf-8 -*-

from dateutil import tz
from datetime import datetime as dt
from h._compat import urlparse

LIMIT_DEFAULT = 20
# Elasticsearch requires offset + limit must be <= 10,000.
LIMIT_MAX = 200
OFFSET_MAX = 9800
DEFAULT_DATE = dt(1970, 1, 1, 0, 0, 0, 0).replace(tzinfo=tz.tzutc())


def wildcard_uri_is_valid(wildcard_uri):
    """
    Return True if uri contains wildcards in appropriate places, return False otherwise.

    *'s and _'s are not permitted in the scheme or netloc aka:
        scheme://netloc/path;parameters?query#fragment.

    If a wildcard is near the begining of a url, elasticsearch will find a large portion of the
    annotations because it is based on luncene which searches from left to right. In order to
    avoid the performance implications of having such a large initial search space, wildcards are
    not allowed in the begining of the url.
    """
    if "*" not in wildcard_uri and "_" not in wildcard_uri:
        return False

    # Note: according to the URL spec _'s are allowed in the domain so this may be
    # something that needs to be supported at a later date.
    normalized_uri = urlparse.urlparse(wildcard_uri)
    if (not normalized_uri.scheme
            or "*" in normalized_uri.netloc
            or "_" in normalized_uri.netloc):
        return False

    return True



