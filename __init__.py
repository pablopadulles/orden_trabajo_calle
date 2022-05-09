# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

from trytond.pool import Pool
from . import orden_trabajo
from . import configuracion


def register():
    Pool.register(orden_trabajo.OrdenTrabajo,
                orden_trabajo.OrdenTrabajoParty,
                configuracion.Configuration,
                configuracion.ConfigurationOTSequence,
                  module='orden_trabajo',
                  type_='model')
    Pool.register(module='orden_trabajo', type_='wizard')
    Pool.register(module='orden_trabajo', type_='report')
