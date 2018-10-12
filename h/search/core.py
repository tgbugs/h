# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import logging
from collections import namedtuple
from contextlib import contextmanager
from elasticsearch.exceptions import ConnectionTimeout
#from webob.multidict import MultiDict

from h.search import query

log = logging.getLogger(__name__)

SearchResult = namedtuple('SearchResult', [
    'total',
    'annotation_ids',
    'reply_ids',
    'aggregations'])


class Search(object):
    """
    Search is the primary way to initiate a search on the annotation index.

    :param request: the request object
    :type request: pyramid.request.Request

    :param separate_replies: Whether or not to return all replies to the
        annotations returned by this search. If this is True then the
        resulting annotations will only include top-level annotations, not replies.
    :type separate_replies: bool

    :param stats: An optional statsd client to which some metrics will be
        published.
    :type stats: statsd.client.StatsClient
    """
    def __init__(self, request, separate_replies=False, stats=None, _replies_limit=200):
        import elasticsearch_dsl
        self.elasticsearch_dsl = elasticsearch_dsl
        self.es = request.es
        self.separate_replies = separate_replies
        self.stats = stats
        self._replies_limit = _replies_limit
        # Order matters! The KeyValueMatcher must be run last,
        # after all other modifiers have popped off the params.
        self._modifiers = [query.Sorter(),
                           query.Limiter(),
                           query.DeletedFilter(),
                           query.AuthFilter(request),
                           query.GroupFilter(),
                           query.GroupAuthFilter(request),
                           query.UserFilter(),
                           query.HiddenFilter(request),
                           query.AnyMatcher(),
                           query.TagsMatcher(),
                           query.KeyValueMatcher()]
        self._aggregations = []

    def run(self, params):
        """
        Execute the search query

        :param params: the search parameters that will be popped by each of the filters.
        :type params: webob.multidict.MultiDict

        :returns: The search results
        :rtype: SearchResult
        """
        total, annotation_ids, aggregations = self._search_annotations(params)
        reply_ids = self._search_replies(annotation_ids)

        return SearchResult(total, annotation_ids, reply_ids, aggregations)

    def clear(self):
        """Clear search modifiers, aggregators, and matchers."""
        self._modifiers = [query.Sorter()]
        self._aggregations = []

    def append_modifier(self, modifier):
        """Append a search modifier, matcher, etc to the search query."""
        # Note we must insert any new modifier at the begining of the list
        # since the KeyValueFilter must always be run after all the other
        # modifiers.
        self._modifiers.insert(0, modifier)

    def append_aggregation(self, aggregation):
        """Append an aggregation to the search query."""
        self._aggregations.append(aggregation)

    def _search(self, modifiers, aggregations, params):
        """
        Applies the modifiers, aggregations, and executes the search.
        """
        # Don't return any fields, just the metadata so set _source=False.
        search = self.elasticsearch_dsl.Search(
            using=self.es.conn, index=self.es.index).source(False)

        for agg in aggregations:
            agg(search, params)
        for qual in modifiers:
            search = qual(search, params)

        response = None
        with self._instrument():
            response = search.execute()

        return response

    def _search_annotations(self, params):
        # If separate_replies is True, don't return any replies to annotations.
        modifiers = self._modifiers
        if self.separate_replies:
            modifiers = [query.TopLevelAnnotationsFilter()] + modifiers

        response = self._search(modifiers,
                                self._aggregations,
                                params)

        total = response['hits']['total']
        annotation_ids = [hit['_id'] for hit in response['hits']['hits']]
        aggregations = self._parse_aggregation_results(response.aggregations)
        return (total, annotation_ids, aggregations)

    def _search_replies(self, annotation_ids):
        if not self.separate_replies:
            return []

        # The only difference between a search for annotations and a search for
        # replies to annotations is the RepliesMatcher and the params passed to
        # the modifiers.
        response = self._search(
            [query.RepliesMatcher(annotation_ids)] + self._modifiers,
            [],  # Aggregations aren't used in replies.
            MultiDict({'limit': self._replies_limit}),
        )

        if len(response['hits']['hits']) < response['hits']['total']:
            log.warning("The number of reply annotations exceeded the page size "
                        "of the Elasticsearch query. We currently don't handle "
                        "this, our search API doesn't support pagination of the "
                        "reply set.")

        return [hit['_id'] for hit in response['hits']['hits']]

    def _parse_aggregation_results(self, aggregations):
        if not aggregations:
            return {}

        results = {}
        for agg in self._aggregations:
            results[agg.name] = agg.parse_result(aggregations)
        return results

    @contextmanager
    def _instrument(self):
        if not self.stats:
            yield
            return

        s = self.stats.pipeline()
        timer = s.timer('search.query').start()
        try:
            yield
            s.incr('search.query.success')
        except ConnectionTimeout:
            s.incr('search.query.timeout')
            raise
        except:  # noqa: E722
            s.incr('search.query.error')
            raise
        finally:
            timer.stop()
            s.send()
