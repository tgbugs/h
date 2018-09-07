# -*- coding: utf-8 -*-
import colander
from h.search.query import LIMIT_DEFAULT, LIMIT_MAX, OFFSET_MAX


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
                       used for pagination.""",
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
    url = colander.SchemaNode(
        colander.Sequence(),
        colander.SchemaNode(colander.String()),
        missing=colander.drop,
        description="Alias of uri.",
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
