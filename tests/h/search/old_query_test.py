# -*- coding: utf-8 -*-

# Most of the tests for `h.search.query` are in `query_test.py` and they
# actually use Elasticsearch. These are the remaining unit tests which mock
# Elasticsearch.

from __future__ import unicode_literals

import mock
import pytest
from hypothesis import strategies as st
from hypothesis import given
from webob import multidict

from h.search import Search, query

ES_VERSION = (1, 7, 0)
MISSING = object()

OFFSET_DEFAULT = 0
LIMIT_DEFAULT = 20
LIMIT_MAX = 200


# TODO - Move these to `query_test.py`.
class IndividualQualifiers(object):
    @pytest.mark.parametrize('offset,from_', [
        # defaults to OFFSET_DEFAULT
        (MISSING, OFFSET_DEFAULT),
        # straightforward pass-through
        (7, 7),
        (42, 42),
        # string values should be converted
        ("23", 23),
        ("82", 82),
        # invalid values should be ignored and the default should be returned
        ("foo",  OFFSET_DEFAULT),
        ("",     OFFSET_DEFAULT),
        ("   ",  OFFSET_DEFAULT),
        ("-23",  OFFSET_DEFAULT),
        ("32.7", OFFSET_DEFAULT),
    ])
    def test_offset(self, offset, from_, search):
        if offset is MISSING:
            params = {}
        else:
            params = {"offset": offset}

        search = query.Limiter()(search, params)
        q = search.to_dict()

        assert q["from"] == from_

    @given(st.text())
    @pytest.mark.fuzz
    def test_limit_output_within_bounds(self, text, search):
        """Given any string input, output should be in the allowed range."""
        params = {"limit": text}

        search = query.Limiter()(search, params)
        q = search.to_dict()

        assert isinstance(q["size"], int)
        assert 0 <= q["size"] <= LIMIT_MAX

    @given(st.integers())
    @pytest.mark.fuzz
    def test_limit_output_within_bounds_int_input(self, lim, search):
        """Given any integer input, output should be in the allowed range."""
        params = {"limit": str(lim)}

        search = query.Limiter()(search, params)
        q = search.to_dict()

        assert isinstance(q["size"], int)
        assert 0 <= q["size"] <= LIMIT_MAX

    @given(st.integers(min_value=0, max_value=LIMIT_MAX))
    @pytest.mark.fuzz
    def test_limit_matches_input(self, lim, search):
        """Given an integer in the allowed range, it should be passed through."""
        params = {"limit": str(lim)}

        search = query.Limiter()(search, params)
        q = search.to_dict()

        assert q["size"] == lim

    def test_limit_missing(self, search):
        params = {}

        search = query.Limiter()(search, params)
        q = search.to_dict()

        assert q["size"] == LIMIT_DEFAULT

    def test_defaults_to_match_all(self, search):
        """If no query params are given a "match_all": {} query is returned."""
        result = search.to_dict()

        assert result == {'query': {'match_all': {}}}

    def test_default_param_action(self, search):
        """Other params are added as "match" clauses."""
        params = {"foo": "bar"}

        search = query.KeyValueMatcher()(search, params)
        q = search.to_dict()

        assert q["query"] == {
            'bool': {'filter': [],
                     'must': [{'match': {'foo': 'bar'}}]},
        }

    def test_default_params_multidict(self, search):
        """Multiple params go into multiple "match" dicts."""
        params = multidict.MultiDict()
        params.add("user", "fred")
        params.add("user", "bob")

        search = query.KeyValueMatcher()(search, params)
        q = search.to_dict()

        assert q["query"] == {
            'bool': {'filter': [],
                     'must': [{'match': {'user': 'fred'}},
                              {'match': {'user': 'bob'}}]},
        }

    def test_with_evil_arguments(self, search):
        params = {
            "offset": "3foo",
            "limit": '\' drop table annotations'
        }

        search = query.Limiter()(search, params)
        q = search.to_dict()

        assert q["from"] == 0
        assert q["size"] == 20
        assert q["query"] == {'bool': {'filter': [], 'must': []}}


class TestSearch(object):
    def test_passes_params_to_matchers(self, search):
        testqualifier = mock.Mock()
        testqualifier.side_effect = lambda search, params: search
        search.append_qualifier(testqualifier)

        search.run({"foo": "bar"})

        testqualifier.assert_called_with(mock.ANY, {"foo": "bar"})

    def test_adds_qualifiers_to_query(self, search):
        testqualifier = mock.Mock()

        search.append_qualifier(testqualifier)

        assert testqualifier in search._qualifiers

    def test_passes_params_to_aggregations(self, search):
        testaggregation = mock.Mock()
        testaggregation.side_effect = lambda search, params: search
        search.append_aggregation(testaggregation)

        search.run({"foo": "bar"})

        testaggregation.assert_called_with(mock.ANY, {"foo": "bar"})

    def test_adds_aggregations_to_query(self, search):
        testaggregation = mock.Mock(key="foobar")

        search.append_aggregation(testaggregation)

        assert testaggregation in search._aggregations


@pytest.fixture
def search(pyramid_request):
    search = Search(pyramid_request)
    # Remove all default filters, aggregators, and matchers.
    search.clear()
    return search
