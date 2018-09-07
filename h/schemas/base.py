# -*- coding: utf-8 -*-

"""Shared functionality for schemas."""

from __future__ import unicode_literals

import copy

import colander
import deform
from pyramid.session import check_csrf_token


@colander.deferred
def deferred_csrf_token(node, kw):
    request = kw.get('request')
    return request.session.get_csrf_token()


class CSRFSchema(colander.Schema):
    """
    A CSRFSchema backward-compatible with the one from the hem module.

    Unlike hem, this doesn't require that the csrf_token appear in the
    serialized appstruct.
    """

    csrf_token = colander.SchemaNode(colander.String(),
                                     widget=deform.widget.HiddenWidget(),
                                     default=deferred_csrf_token,
                                     missing=None)

    def validator(self, form, value):
        request = form.bindings['request']
        check_csrf_token(request)


def enum_type(enum_cls):
    """
    Return a `colander.Type` implementation for a field with a given enum type.

    :param enum_cls: The enum class
    :type enum_cls: enum.Enum
    """
    class EnumType(colander.SchemaType):
        def deserialize(self, node, cstruct):
            if cstruct == colander.null:
                return None

            try:
                return enum_cls[cstruct]
            except KeyError:
                msg = '"{}" is not a known value'.format(cstruct)
                raise colander.Invalid(node, msg)

        def serialize(self, node, appstruct):
            if not appstruct:
                return ''
            return appstruct.name

    return EnumType
