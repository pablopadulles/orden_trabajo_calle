from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta, date
try:
    from urllib.parse import urlencode
except ImportError:
    from urlparse import urlparse
try:
    from urllib.parse import urlunparse
except ImportError:
    from urlparse import urlunparse
from collections import OrderedDict
from io import BytesIO

try:
    from PIL import Image
except ImportError:
    Image = None
from sql import Literal, Join, Table, Null
from sql.functions import Overlay, Position

from trytond.model import ModelView, ModelSingleton, ModelSQL, fields, Unique, Workflow, MultiValueMixin, ValueMixin
from trytond.wizard import Wizard, StateAction, StateView, Button
from trytond.transaction import Transaction
from trytond import backend
from trytond.pyson import Eval, Not, Bool, PYSONEncoder, Equal, And, Or, If
from trytond.pool import Pool, PoolMeta
from trytond.tools import grouped_slice, reduce_ids
from trytond.backend import name as backend_name

from uuid import uuid4
import string
import random
import pytz


sequence_ot = fields.Many2One(
        'ir.sequence', 'Numero OT', required=True,
        )


# SEQUENCES
class Configuration(ModelSingleton, ModelSQL, ModelView, MultiValueMixin):
    'Configuration'
    __name__ = 'orden.trabajo.configuration'

    sequence_ot = fields.MultiValue(sequence_ot)

    @classmethod
    def default_sequence_ot(cls, **pattern):
        pool = Pool()
        ModelData = pool.get('ir.model.data')
        try:
            return ModelData.get_id('orden_trabajo', 'sequence_ot')
        except KeyError:
            return None


class ConfigurationOTSequence(ModelSQL, ValueMixin):
    'Configuration Sequence OT'
    __name__ = 'orden.trabajo.configuration.sequence_ot'

    sequence_ot = sequence_ot

    @classmethod
    def check_xml_record(cls, records, values):
        return True
