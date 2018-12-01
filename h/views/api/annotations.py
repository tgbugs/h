# -*- coding: utf-8 -*-

"""
HTTP/REST API for storage and retrieval of annotation data.

This module contains the views which implement our REST API, mounted by default
at ``/api``. Currently, the endpoints are limited to:

- basic CRUD (create, read, update, delete) operations on annotations
- annotation search
- a handful of authentication related endpoints

It is worth noting up front that in general, authorization for requests made to
each endpoint is handled outside of the body of the view functions. In
particular, requests to the CRUD API endpoints are protected by the Pyramid
authorization system. You can find the mapping between annotation "permissions"
objects and Pyramid ACLs in :mod:`h.traversal`.
"""
from __future__ import unicode_literals
import colander
from pyramid import i18n
import newrelic.agent

from h import search as search_lib
from h import storage
from h.exceptions import PayloadError
from h.events import AnnotationEvent
from h.interfaces import IGroupService
from h.presenters import AnnotationJSONLDPresenter
from h.traversal import AnnotationContext
from h.schemas.util import validate_query_params
from h.schemas.annotation import (
    CreateAnnotationSchema,
    UpdateAnnotationSchema)
from h.views.api.config import api_config

_ = i18n.TranslationStringFactory(__package__)


class SearchParamsSchema(colander.Schema):
    _separate_replies = colander.SchemaNode(
        colander.Boolean(),
        missing=False,
        description="Return a separate set of annotations and their replies.",
    )
    sort = colander.SchemaNode(
        colander.String(),
        validator=colander.OneOf(["created", "updated", "group", "id", "user"]),
        missing="updated",
        description="The field by which annotations should be sorted.",
    )
    search_after = colander.SchemaNode(
        colander.String(),
        missing=colander.drop,
        description="""Returns results after the annotation who's sort field
                    has this value. If specifying a date use the format
                    yyyy-MM-dd'T'HH:mm:ss.SSX or time in miliseconds since the
                    epoch. This is used for iteration through large collections
                    of results.""",
    )
    limit = colander.SchemaNode(
        colander.Integer(),
        validator=colander.Range(min=0, max=LIMIT_MAX),
        missing=LIMIT_DEFAULT,
        description="The maximum number of annotations to return.",
    )
    order = colander.SchemaNode(
        colander.String(),
        validator=colander.OneOf(["asc", "desc"]),
        missing="desc",
        description="The direction of sort.",
    )
    offset = colander.SchemaNode(
        colander.Integer(),
        validator=colander.Range(min=0, max=OFFSET_MAX),
        missing=0,
        description="""The number of initial annotations to skip. This is
                       used for pagination. Not suitable for paging through
                       thousands of annotations-search_after should be used
                       instead.""",
    )
    group = colander.SchemaNode(
        colander.String(),
        missing=colander.drop,
        description="Limit the results to this group of annotations.",
    )
    quote = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="""Limit the results to annotations that contain this text inside
                        the text that was annotated.""",
    )
    references = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="""Returns annotations that are replies to this parent annotation id.""",
    )
    tag = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="Limit the results to annotations tagged with the specified value.",
    )
    tags = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="Alias of tag.",
    )
    text = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="Limit the results to annotations that contain this text in their textual body.",
    )
    uri = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="""Limit the results to annotations matching the specific URI
                       or equivalent URIs. URI can be a URL (a web page address) or
                       a URN representing another kind of resource such as DOI
                       (Digital Object Identifier) or a PDF fingerprint.""",
    )
    uri_parts = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        name='uri.parts',
        missing=colander.drop,
        description="""Limit the results to annotations with the given keyword
                       appearing in the URL.""",
    )
    url = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="Alias of uri.",
    )
    wildcard_uri = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        validator=_validate_wildcard_uri,
        missing=colander.drop,
        description="""
            Limit the results to annotations matching the wildcard URI.
            URI can be a URL (a web page address) or a URN representing another
            kind of resource such as DOI (Digital Object Identifier) or a
            PDF fingerprint.

            `*` will match any character sequence (including an empty one),
            and a `_` will match any single character. Wildcards are only permitted
            within the path and query parts of the URI.

            Escaping wildcards is not supported.

            Examples of valid uris":" `http://foo.com/*` `urn:x-pdf:*` `file://localhost/_bc.pdf`
            Examples of invalid uris":" `*foo.com` `u_n:*` `file://*` `http://foo.com*`
            """,
    )
    any = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="""Limit the results to annotations whose quote, tags,
                       text or url fields contain this keyword.""",
    )
    user = colander.SchemaNode(
        colander.String(),
        missing=colander.drop,
        description="Limit the results to annotations made by the specified user.",
    )

    def validator(self, node, cstruct):
        sort = cstruct['sort']
        search_after = cstruct.get('search_after', None)

        if search_after:
            if sort in ["updated", "created"] and not self._date_is_parsable(search_after):
                raise colander.Invalid(
                    node,
                    """search_after must be a parsable date in the form
                    yyyy-MM-dd'T'HH:mm:ss.SSX
                    or time in miliseconds since the epoch.""")

            # offset must be set to 0 if search_after is specified.
            cstruct["offset"] = 0

    def _date_is_parsable(self, value):
        """Return True if date is parsable and False otherwise."""

        # Dates like "2017" can also be cast as floats so if a number is less
        # than 9999 it is assumed to be a year and not ms since the epoch.
        try:
            if float(value) < 9999:
                raise ValueError("This is not in the form ms since the epoch.")
        except ValueError:
            try:
                parse(value)
            except ValueError:
                return False
        return True


@api_config(route_name='api.search',
            link_name='search',
            description='Search for annotations')
def search(request):
    """Search the database for annotations matching with the given query."""
    schema = SearchParamsSchema()
    params = validate_query_params(schema, request.params)

    _record_search_api_usage_metrics(params)

    separate_replies = params.pop('_separate_replies', False)

    stats = getattr(request, 'stats', None)

    search = search_lib.Search(request,
                               separate_replies=separate_replies,
                               stats=stats)
    result = search.run(params)

    svc = request.find_service(name='annotation_json_presentation')

    out = {
        'total': result.total,
        'rows': svc.present_all(result.annotation_ids)
    }

    if separate_replies:
        out['replies'] = svc.present_all(result.reply_ids)

    return out


@api_config(route_name='api.annotations',
            request_method='POST',
            permission='create',
            link_name='annotation.create',
            description='Create an annotation')
def create(request):
    """Create an annotation from the POST payload."""
    schema = CreateAnnotationSchema(request)
    appstruct = schema.validate(_json_payload(request))
    group_service = request.find_service(IGroupService)
    annotation = storage.create_annotation(request, appstruct, group_service)

    _publish_annotation_event(request, annotation, 'create')

    svc = request.find_service(name='annotation_json_presentation')
    annotation_resource = _annotation_resource(request, annotation)
    return svc.present(annotation_resource)


@api_config(route_name='api.annotation',
            request_method='GET',
            permission='read',
            link_name='annotation.read',
            description='Fetch an annotation')
def read(context, request):
    """Return the annotation (simply how it was stored in the database)."""
    svc = request.find_service(name='annotation_json_presentation')
    return svc.present(context)


@api_config(route_name='api.annotation.jsonld',
            request_method='GET',
            permission='read')
def read_jsonld(context, request):
    request.response.content_type = 'application/ld+json'
    request.response.content_type_params = {
        'charset': 'UTF-8',
        'profile': str(AnnotationJSONLDPresenter.CONTEXT_URL)}
    presenter = AnnotationJSONLDPresenter(context)
    return presenter.asdict()


@api_config(route_name='api.annotation',
            request_method=('PATCH', 'PUT'),
            permission='update',
            link_name='annotation.update',
            description='Update an annotation')
def update(context, request):
    """Update the specified annotation with data from the PATCH payload."""
    if request.method == 'PUT' and hasattr(request, 'stats'):
        request.stats.incr('api.deprecated.put_update_annotation')

    schema = UpdateAnnotationSchema(request,
                                    context.annotation.target_uri,
                                    context.annotation.groupid)
    appstruct = schema.validate(_json_payload(request))
    group_service = request.find_service(IGroupService)

    annotation = storage.update_annotation(request,
                                           context.annotation.id,
                                           appstruct,
                                           group_service)

    _publish_annotation_event(request, annotation, 'update')

    svc = request.find_service(name='annotation_json_presentation')
    annotation_resource = _annotation_resource(request, annotation)
    return svc.present(annotation_resource)


@api_config(route_name='api.annotation',
            request_method='DELETE',
            permission='delete',
            link_name='annotation.delete',
            description='Delete an annotation')
def delete(context, request):
    """Delete the specified annotation."""
    storage.delete_annotation(request.db, context.annotation.id)

    # N.B. We publish the original model (including all the original annotation
    # fields) so that queue subscribers have context needed to decide how to
    # process the delete event. For example, the streamer needs to know the
    # target URLs of the deleted annotation in order to know which clients to
    # forward the delete event to.
    _publish_annotation_event(
        request,
        context.annotation,
        'delete')

    # TODO: Track down why we don't return an HTTP 204 like other DELETEs
    return {'id': context.annotation.id, 'deleted': True}


def _json_payload(request):
    """
    Return a parsed JSON payload for the request.

    :raises PayloadError: if the body has no valid JSON body
    """
    try:
        return request.json_body
    except ValueError:
        raise PayloadError()


def _publish_annotation_event(request,
                              annotation,
                              action):
    """Publish an event to the annotations queue for this annotation action."""
    event = AnnotationEvent(request, annotation.id, action)
    request.notify_after_commit(event)


def _annotation_resource(request, annotation):
    group_service = request.find_service(IGroupService)
    links_service = request.find_service(name='links')
    return AnnotationContext(annotation, group_service, links_service)


def _record_search_api_usage_metrics(
    params,
    record_param=newrelic.agent.add_custom_parameter,
):
    # Record usage of search params and associate them with a transaction.
    keys = [
        # Record usage of inefficient offset and it's alternative search_after.
        "offset",
        "search_after",
        "sort",
        # Record usage of url/uri (url is an alias of uri).
        "url",
        "uri",
        # Record usage of tags/tag (tags is an alias of tag).
        "tags",
        "tag",
        # Record usage of _separate_replies which will help distinguish client calls
        # for loading the sidebar annotations from other api calls.
        "_separate_replies",
        # Record group and user-these help in identifying slow queries.
        "group",
        "user",
        # Record usage of wildcard feature.
        "wildcard_uri",
    ]

    for k in keys:
        if k in params:
            # The New Relic Query Language does not permit _ at the begining
            # and offset is a reserved key word.
            record_param("es_{}".format(k), str(params[k]))
