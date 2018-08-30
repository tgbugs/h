# -*- coding: utf-8 -*-

from __future__ import unicode_literals
from h import storage
from h.util import uri
from elasticsearch_dsl import Q
from elasticsearch_dsl.query import SimpleQueryString

LIMIT_DEFAULT = 20
LIMIT_MAX = 200


class KeyValueMatcher(object):
    """
    Adds any parameters as straightforward key-value matchers.

    This is intended to be run after all other matchers so that any
    remaining params not popped by any other qualifier get dealt with here.
    """

    def __call__(self, search, params):
        for key, value in params.items():
            search = search.filter("match", **{key: value})
        return search


class Limiter(object):
    """
    Limits the number of annotations returned by the search.

    Searchers for annotations starting at offset and ending at limit.
    """

    def __call__(self, search, params):
        starting_offset = self._extract_offset(params)
        ending_offset = starting_offset + self._extract_limit(params)
        return search[starting_offset:ending_offset]

    def _extract_offset(self, params):
        try:
            val = int(params.pop("offset"))
            if val < 0:
                raise ValueError
        except (ValueError, KeyError):
            return 0
        else:
            return val

    def _extract_limit(self, params):
        try:
            val = int(params.pop("limit"))
            val = min(val, LIMIT_MAX)
            if val < 0:
                raise ValueError
        except (ValueError, KeyError):
            return LIMIT_DEFAULT
        else:
            return val


class Sorter(object):
    """
    Sorts annotations.

    Sorts annotations by sort (the key to sort by)
    and the order (the order in which to sort by).
    """

    def __call__(self, search, params):
        return search.sort({
            params.pop("sort", "updated"): {
                "order": params.pop("order", "desc"),

                # `unmapped_type` causes unknown fields specified as arguments to
                # `sort` behave as if all documents contained empty values of the
                # given type. Without this, specifying eg. `sort=foobar` throws
                # an exception.
                #
                # We use the field type `boolean` to assist with migration because
                # that exists in both ES 1 and ES 6.
                "unmapped_type": "boolean",
            }
        })


class TopLevelAnnotationsFilter(object):

    """Matches top-level annotations only, filters out replies."""

    def __call__(self, search, _):
        return search.exclude("exists", field="references")


class AuthorityFilter(object):

    """
    Match only annotations created by users belonging to a specific authority.
    """

    def __init__(self, authority):
        self.authority = authority

    def __call__(self, search, params):
        return search.filter("term", authority=self.authority)


class AuthFilter(object):

    """
    A filter that selects only annotations the user is authorised to see.

    Only annotations that are shared, or private annotations made
    by the logged-in user will pass through this filter.
    """

    def __init__(self, request):
        """
        Initialize a new AuthFilter.

        :param request: the pyramid.request object
        """
        self.request = request

    def __call__(self, search, params):
        userid = self.request.authenticated_userid
        if userid is None:
            return search.filter("term", shared=True)

        return search.filter(Q("bool",
                               should=[Q("term", shared=True),
                                       Q("term", user_raw=userid)]))


class GroupFilter(object):

    """
    Matches only those annotations belonging to the specified group.
    """

    def __call__(self, search, params):
        # Remove parameter if passed, preventing fall-through to default query
        group = params.pop("group", None)

        if group is not None:
            return search.filter("term", group=group)
        return search


class GroupAuthFilter(object):
    """Filter out groups that the request isn't authorized to read."""

    def __init__(self, request):
        self.user = request.user
        self.group_service = request.find_service(name="group")

    def __call__(self, search, _):
        groups = self.group_service.groupids_readable_by(self.user)
        return search.filter("terms", group=groups)


class UriWildcardFilter(object):

    """
    A filter that selects only annotations where the 'site' parameter matches as *site*.
    """

    def __init__(self, request):
        """Searches for wildcard uri's.

        :param request: the pyramid.request object

        """
        self.request = request

    def __call__(self, search, params):
        query_uris = params.getall('wildcard_uri')

        uris = set()
        for query_uri in query_uris:
            expanded = storage.expand_uri(self.request.db, query_uri)

            us = [uri.normalize(u) for u in expanded]
            uris.update(us)

        return search.query(Q('bool', should=[Q('wildcard', **{"target.scope": u}) for u in uris]))


class UriFilter(object):

    """
    A filter that selects only annotations where the 'uri' parameter matches.
    """

    def __init__(self, request):
        """Initialize a new UriFilter.

        :param request: the pyramid.request object

        """
        self.request = request

    def __call__(self, search, params):
        if 'uri' not in params and 'url' not in params:
            return search
        query_uris = [v for k, v in params.items() if k in ['uri', 'url']]
        if 'uri' in params:
            del params['uri']
        if 'url' in params:
            del params['url']

        uris = set()
        for query_uri in query_uris:
            expanded = storage.expand_uri(self.request.db, query_uri)

            us = [uri.normalize(u) for u in expanded]
            uris.update(us)
        return search.filter(
            'terms', **{'target.scope': list(uris)})


class UserFilter(object):

    """
    A filter that selects only annotations where the 'user' parameter matches.
    """

    def __call__(self, search, params):
        if 'user' not in params:
            return search

        users = [v.lower() for k, v in params.items() if k == 'user']
        del params['user']

        return search.filter("terms", user=users)


class DeletedFilter(object):

    """
    A filter that only returns non-deleted documents.

    Documents are not getting deleted from the index, they only get marked as
    deleted.
    """

    def __call__(self, search, _):
        return search.exclude("exists", field="deleted")


class NipsaFilter(object):
    def __init__(self, request):
        self.group_service = request.find_service(name='group')
        self.user = request.user

    def __call__(self, search, _):
        return self._nipsa_filter(search, self.group_service, self.user)

    def _nipsa_filter(self, search, group_service, user=None):
        """Return an Elasticsearch filter for filtering out NIPSA'd annotations.

        The returned filter is suitable for inserting into an Es query dict.
        For example:

            query = {
                "query": {
                    "filtered": {
                        "filter": nipsa_filter(),
                        "query": {...}
                    }
                }
             }

        :param user: The user whose annotations should not be filtered.
           The returned filtered query won't filter out this user's annotations,
            even if the annotations have the NIPSA flag.
        :type user: h.models.User
        """
        # If any one of these "should" clauses is true then the annotation will
        # get through the filter.
        should_clauses = [Q("bool", must_not=Q("term", nipsa=True)),
                          Q("exists", field="thread_ids")]

        if user is not None:
            # Always show the logged-in user's annotations even if they have nipsa.
            should_clauses.append(Q("term", user=user.userid.lower()))

            # Also include nipsa'd annotations for groups that the user created.
            created_groups = group_service.groupids_created_by(user)
            if created_groups:
                should_clauses.append(Q("terms", group=created_groups))

        return search.filter(Q("bool", should=should_clauses))


class AnyMatcher(object):

    """
    Matches the contents of a selection of fields against the `any` parameter.
    """

    def __call__(self, search, params):
        if "any" not in params:
            return search
        qs = ' '.join([v for k, v in params.items() if k == "any"])
        del params["any"]
        return search.query(
            SimpleQueryString(
                query=qs,
                fields=["quote", "tags", "text", "uri.parts"],
                # default_operator='or',
            )
        )


class TagsMatcher(object):

    """Matches the tags field against 'tag' or 'tags' parameters."""

    def __call__(self, search, params):
        tags = set(v for k, v in params.items() if k in ['tag', 'tags'])
        try:
            del params['tag']
            del params['tags']
        except KeyError:
            pass
        matchers = [Q("match", tags={"query": t, "operator": "and"})
                    for t in tags]
        if matchers:
            return search.query(
                Q('bool', must=matchers)
            )
        return search


class RepliesMatcher(object):

    """Matches any replies to any of the given annotation ids."""

    def __init__(self, ids):
        self.annotation_ids = ids

    def __call__(self, search, _):
        return search.query(
            Q('bool', must=[Q('terms', references=self.annotation_ids)])
        )


class TagsAggregation(object):
    def __init__(self, limit=10):
        self.limit = limit
        self.name = "tags"

    def __call__(self, search, _):
        search.aggs.bucket(self.name, 'terms', size=self.limit, field='tags_raw')

    def parse_result(self, result):
        return [
            {'tag': b["key"], 'count': b["doc_count"]}
            for b in result[self.name]["buckets"]
        ]


class UsersAggregation(object):
    def __init__(self, limit=10):
        self.limit = limit
        self.name = "users"

    def __call__(self, search, _):
        search.aggs.bucket(self.name, 'terms', size=self.limit, field='user_raw')

    def parse_result(self, result):
        return [
            {'user': b["key"], 'count': b["doc_count"]}
            for b in result[self.name]["buckets"]
        ]
