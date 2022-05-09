from dataclasses import field
from stdnum import get_cc_module
import stdnum.exceptions
import logging
from sql import Null, Column, Literal
from sql.functions import CharLength, Substring, Position
from datetime import datetime, timedelta
from trytond.i18n import gettext
from trytond.model import (ModelView, ModelSQL, MultiValueMixin, ValueMixin,
    DeactivableMixin, fields, Unique, sequence_ordered, Workflow, ModelSingleton)
from trytond.wizard import Wizard, StateTransition, StateView, Button
from trytond.pyson import Eval, Bool, Not, Or
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond import backend
from trytond.tools.multivalue import migrate_property
from trytond.tools import lstrip_wildcard
import xlrd

logger = logging.getLogger(__name__)


class OrdenTrabajo(Workflow, ModelView, ModelSQL):
    'Orden de Trabajo'
    __name__ = 'orden.trabajo'

    code = fields.Char('Numero OT Automatico', states={"readonly":True})
    name = fields.Char('Numero OT')
    date = fields.Date('Fecha')
    datetime_start = fields.DateTime('Fecha Inicio')
    datetime_finish = fields.DateTime('Fecha Fin')
    street = fields.Char("Street")
    aviso_señalamiento = fields.Boolean("Aviso de Señalamiento")
    active = fields.Boolean("Activo")
    city = fields.Char("City")
    central = fields.Many2One('oci.central.telecom', 'Zona',
                      states={'readonly':Eval('state').in_(['done'])})
    armario = fields.Many2One('oci.armario', 'Armario', domain=[
            ('central', '=', Eval('central')),
        ], states={'readonly':Eval('state').in_(['done'])})
    observaciones = fields.Text('Observaciones', states={'readonly':Eval('state').in_(['done'])})
    # Cuadrilla    
    tecnico_sup = fields.Many2One('party.party', 'Tecnico Supervisor',
        domain=[('perfil', '=', 'tec')])
    tecnicos = fields.Many2Many('orden.trabajo-party.party',
            'orden_trabajo', 'party', 'Tecnicos',
            domain=[('perfil', '=', 'tec')])
    
    products = fields.Function(fields.Many2Many('product.product', None, None, 'Productos',
                states={'invisible':True}), 'on_change_with_products')
    materiales = fields.One2Many('oci.materiales', 'name', 'Materiales',
        states={'readonly': Or(Eval('state').in_(['done']), ~Bool(Eval('tecnico_sup')))})

    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('done', 'Done')], 'State', readonly=True)
    

    @classmethod
    def __setup__(cls):
        super(OrdenTrabajo, cls).__setup__()
        cls._transitions |= set((
            ('draft', 'open'),
            ('open', 'done'),
            ))

        cls._buttons.update({
            'open': {
                'invisible': Eval('state').in_(['open', 'done'])
                },
            'done': {
                'invisible': Eval('state').in_(['draft', 'done'])
                },
            })


    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_active():
        return True

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, ot):
        pass    

    @classmethod
    @ModelView.button
    @Workflow.transition('open')
    def open(cls, ots):
        for ot in ots:
            ot.code = cls._new_code()
            ot.save()
    
    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, ot):
        pass

    @fields.depends('tecnico_sup')
    def on_change_with_products(self, name=None):
        Product = Pool().get('product.product')
        materiales = []
        if not self.tecnico_sup:
            return []
        return self.get_materiales(self.tecnico_sup)
        # if self.tecnico.deposito:
        #     stock = Product.products_by_location([self.tecnico.deposito.id])
        #     for k in stock.keys():
        #         if stock.get(k) > 0:
        #             materiales.append(k[1])
        # return materiales

    @classmethod
    def get_materiales(cls, tecnico_id):
        Product = Pool().get('product.product')
        Party = Pool().get('party.party')
        materiales = []
        tecnico = Party(tecnico_id)
        if tecnico.deposito:
            stock = Product.products_by_location([tecnico.deposito.id])
            for k in stock.keys():
                if stock.get(k) > 0:
                    materiales.append(k[1])
        return materiales


    @classmethod
    def _new_code(cls, **pattern):
        pool = Pool()
        Configuration = pool.get('orden.trabajo.configuration')
        config = Configuration(1)
        sequence = config.get_multivalue('sequence_ot', **pattern)
        if sequence:
            return sequence.get()

    # @classmethod
    # def create(cls, vlist):
    #     vlist = [x.copy() for x in vlist]
    #     for values in vlist:
    #         if not values.get('code'):
    #             values['code'] = cls._new_code()
    #     return super(OrdenTrabajo, cls).create(vlist)


class OrdenTrabajoParty(ModelSQL):
    'Orden Trabajo - Party'
    __name__ = 'orden.trabajo-party.party'
    _table = 'orden_trabajo_party_party_rel'

    orden_trabajo = fields.Many2One('orden.trabajo', 'Orden Trabajo')
    party = fields.Many2One('party.party', 'Party')
