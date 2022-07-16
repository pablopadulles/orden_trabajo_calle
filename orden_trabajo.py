from dataclasses import field
from re import template
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
from trytond.pyson import Eval, Bool, Not, Or, If
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

    type = fields.Selection([('postacion', 'Postacion'),('siniestro', 'Siniestro')], 'Tipo',
        states={'invisible':True})
    code = fields.Char('Numero OT Automatico', states={"readonly":True})
    name = fields.Char('EHS', states={"required":True})
    io = fields.Char('IO', states={"required":True})
    date = fields.Date('Fecha')
    date_execution = fields.Date('Fecha de Ejecución')
    datetime_start = fields.Timestamp('Fecha Inicio', states={"readonly":True})
    datetime_finish = fields.Timestamp('Fecha Fin', states={"readonly":True})
    street = fields.Char("Street")
    aviso_señalamiento = fields.Boolean("Aviso de Señalamiento")
    active = fields.Boolean("Activo")
    city = fields.Char("City")
    central = fields.Many2One('oci.central.telecom', 'Zona',
                      states={'readonly':Eval('state').in_(['done'])})
    shipment_out = fields.Many2One('stock.shipment.out', 'Remito Materiales', states={"readonly":True})
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
    materiales = fields.One2Many('orden.trabajo.materiales', 'name', 'Materiales',
        states={'readonly': Eval('state').in_(['validated', 'start', 'done'])})

    prioriry = fields.Selection([
        ('1', 'Low'),
        ('2', 'Medium'),
        ('3', 'High'),
        ('4', 'Urgent')], 'Priority', required=True, sort=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('open', 'Open'),
        ('validated', 'Validated'),
        ('start', 'Start'),
        ('done', 'Done')], 'State', readonly=True)
    
    @classmethod
    def __setup__(cls):
        super(OrdenTrabajo, cls).__setup__()
        cls._order.insert(0, ('date_execution', 'ASC'))
        cls._order.insert(1, ('code', 'ASC'))

        cls._transitions |= set((
            ('draft', 'open'),
            ('open', 'validated'),
            ('validated', 'start'),
            ('start', 'done'),
            ))

        cls._buttons.update({
            'open': {
                'invisible': Not(Eval('state').in_(['draft']))
                },
            'validated': {
                'invisible': Not(Eval('state').in_(['open']))
                },
            'start': {
                'invisible': Not(Eval('state').in_(['validated']))
                },
            'done': {
                'invisible': Not(Eval('state').in_(['start']))
                },
            })

    @classmethod
    def view_attributes(cls):
        return super().view_attributes() + [
            ('/tree', 'visual',
                If(
                    Eval('prioriry') == '1', 'muted',
                    If(
                        Eval('prioriry') == '2', 'success', 
                        If(
                            Eval('prioriry') == '3', 'warning', 
                            If(
                                Eval('prioriry') == '4', 'danger', ''))
                    ),
                )
            )]

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_prioriry():
        return '1'

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
    @Workflow.transition('validated')
    def validated(cls, ots):
        for ot in ots:
            moves = []
            if not ot.tecnico_sup:
                raise ValueError('Falta el tecnico supervisor')
            if not ot.date_execution:
                raise ValueError('Falta la Fecha de Ejecución')
            Remito = Pool().get('stock.shipment.out')
            delivery_address = ot.tecnico_sup.address_get(type='delivery')
            remito, = Remito.create([{
                'customer':ot.tecnico_sup,
                'reference':ot.code,
                'delivery_address': delivery_address.id,
                # 'moves':[('create', moves)]
            }])
            for material in ot.materiales:
                moves.append({
                    'product': material.insumo.id,
                    'uom': material.insumo.template.default_uom.id,
                    'quantity': float(material.cantidad),
                    'unit_price': 0.0,
                    'from_location':remito.warehouse_output,
                    'to_location':remito.customer_location
                })
            remito.moves = moves
            remito.save()
            Remito.wait([remito])
            ot.shipment_out = remito
            ot.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('start')
    def start(cls, ots):
        Date = Pool().get('ir.date')
        for ot in ots:
            ot.datetime_start = datetime.now()
            ot.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, ots):
        Date = Pool().get('ir.date')
        for ot in ots:
            ot.datetime_finish = datetime.now()
            Materiales = Pool().get('oci.materiales')
            Materiales.done(ot.materiales)
            ot.save()

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


# class Materiales(metaclass=PoolMeta):
#     __name__ = 'oci.materiales'

#     name_ot = fields.Many2One('orden.trabajo', 'OT', ondelete='CASCADE')

#     @classmethod
#     def __setup__(cls):
#         super(Materiales, cls).__setup__()
#         cls.insumo.domain = [
#             If(Eval('_parent_name', False),
#                 ('id', 'in', Eval('_parent_name', {}).get('products')),
#                 ('id', 'in', Eval('_parent_name_ot', {}).get('products')))
#             ]

#     @classmethod
#     @ModelView.button
#     @Workflow.transition('done')
#     def done(cls, materiales):
#         Move = Pool().get('stock.move')
#         Date = Pool().get('ir.date')
#         list = []
#         company = Transaction().context.get('company')
#         for material in materiales:
#             if material.state == 'done':
#                 continue
#             list.append({
#             'product': material.insumo.id,
#             'uom': material.insumo.template.default_uom.id,
#             'quantity': material.cantidad,
#             'from_location': material.name.tecnico.deposito.id if material.name else material.name_ot.tecnico_sup.deposito.id,
#             'to_location': 7, #Cliente
#             'effective_date': Date.today(),
#             'company': company,
#             'unit_price': material.insumo.template.list_price,
#             })

#         moves = Move.create(list)
#         Move.do(moves)
#         pass


class Materiales(ModelSQL, ModelView):
    "Materiales para a orden de trabajo"
    __name__ = 'orden.trabajo.materiales'

    name = fields.Many2One('orden.trabajo', 'OT', ondelete='CASCADE')
    insumo = fields.Many2One('product.product', 'Insumo', required=True)
    cantidad = fields.Integer('Cantidad', required=True)
