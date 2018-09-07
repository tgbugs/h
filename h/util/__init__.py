# -*- coding: utf-8 -*-

from __future__ import unicode_literals
from h.util import db
from h.util import user
#from h.util import view
# the thing that is annoying about this pattern is that it forces anything importing a submodule
# to also transiently import all of this stuff as well, even if it would not be used ...

__all__ = ('db', 'user', 'view')
