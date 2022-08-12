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
from trytond.pyson import Eval, Bool, Not, Or, If, Equal
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
from trytond import backend
from trytond.tools.multivalue import migrate_property
from trytond.tools import lstrip_wildcard

logger = logging.getLogger(__name__)


class OrdenTrabajo(Workflow, ModelView, ModelSQL):
    'Orden de Trabajo'
    __name__ = 'orden.trabajo'
    _rec_name = 'code'

    type = fields.Selection([('postacion', 'Postacion'),('siniestro', 'Siniestro')], 'Tipo',
        states={'invisible':True})
    code = fields.Char('Numero OT Automatico', states={"readonly":True})
    pedido_por = fields.Char('Pedido Por', states={"required":Equal(Eval('type'), 'postacion')})
    name = fields.Char('EHS', states={"required":Equal(Eval('type'), 'siniestro')})
    oi = fields.Char('OI', states={"required":Equal(Eval('type'), 'siniestro')})
    date = fields.Date('Fecha')
    date_execution = fields.Date('Fecha de Ejecución')
    datetime_start = fields.Timestamp('Fecha Inicio', states={"readonly":True})
    datetime_finish = fields.Timestamp('Fecha Fin', states={"readonly":True})
    street = fields.Char("Street")
    # aviso_señalamiento = fields.Boolean("Aviso de Señalamiento")
    aviso_señalamiento = fields.Integer("AS", states={'required':Equal(Eval('type'), 'postacion')})
    numero_ot = fields.Integer("OT", states={'required':Equal(Eval('type'), 'postacion')})
    active = fields.Boolean("Activo")
    city = fields.Char("City")
    central = fields.Many2One('oci.central.telecom', 'Zona',
                      states={'readonly':Eval('state').in_(['done'])})
    
    shipments_out = fields.Many2Many('orden.trabajo-stock.shipment.out', 'orden_trabajo', 
            'shipment_out', 'Remitos Materiales', states={"readonly":True})
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
        states={'readonly': Eval('state').in_(['done'])})
    workers = fields.One2Many('orden.trabajo.workers', 'name', 'Trabajadores',
        states={'readonly': True})

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
        ('stop', 'Stop'),
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
            ('start', 'stop'),
            ('stop', 'start'),
            ('start', 'done'),
            ))

        cls._buttons.update({
            'agregar_materiales': {
                'invisible': Not(Eval('state').in_(['validated'])),
                'readonly': Eval('state').in_(['done'])
                },
            'open': {
                'invisible': Not(Eval('state').in_(['draft']))
                },
            'validated': {
                'invisible': Not(Eval('state').in_(['open']))
                },
            'start': {
                'invisible': Not(Eval('state').in_(['validated']))
                },
            'stop': {
                'invisible': Not(Eval('state').in_(['start']))
                },
            'resume': {
                'invisible': Not(Eval('state').in_(['stop']))
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
    def default_date():
        return Pool().get('ir.date').today()

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
    @ModelView.button_action('orden_trabajo.wiz_orden_trabajo_agregar_materiales')
    def agregar_materiales(cls, entries):
        pass

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
    @Workflow.transition('stop')
    def stop(cls, ots):
        now = datetime.now()
        for ot in ots:
            for worker in ot.workers:
                worker.fecha_hora_fin = now
                worker.save()
            ot.save()
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('resume')
    def resume(cls, ots):
        OTW = Pool().get('orden.trabajo.workers')
        now = datetime.now()
        for ot in ots:
            vals = [{'name': ot.id,
                'party': ot.tecnico_sup.id,
                'fecha_hora_inicio': now
                }]
            for tecnico in ot.tecnicos:
                vals.append({'name': ot.id,
                'party': tecnico.id,
                'fecha_hora_inicio': now
                })
            OTW.create(vals) 
            ot.save()
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('validated')
    def validated(cls, ots):
        for ot in ots:
            if not ot.tecnico_sup:
                raise ValueError('Falta el tecnico supervisor')
            if not ot.date_execution:
                raise ValueError('Falta la Fecha de Ejecución')
            ot.crear_remito()

    @classmethod
    @ModelView.button
    @Workflow.transition('start')
    def start(cls, ots):
        OTW = Pool().get('orden.trabajo.workers')
        now = datetime.now()
        for ot in ots:
            vals = [{'name': ot.id,
                'party': ot.tecnico_sup.id,
                'fecha_hora_inicio': now
                }]
            for tecnico in ot.tecnicos:
                vals.append({'name': ot.id,
                'party': tecnico.id,
                'fecha_hora_inicio': now
                })

            OTW.create(vals) 
            ot.datetime_start = now
            ot.save()

    @classmethod
    @ModelView.button
    @Workflow.transition('done')
    def done(cls, ots):
        
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

    def crear_remito(self) -> bool:
        try:
            moves = []
            Remito = Pool().get('stock.shipment.out')
            delivery_address = self.tecnico_sup.address_get(type='delivery')
            remito, = Remito.create([{
                'customer':self.tecnico_sup,
                'reference':self.code,
                'delivery_address': delivery_address.id,
                # 'moves':[('create', moves)]
            }])
            for material in self.materiales:
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
            OrdenTrabajoStockShipmentOut.create([{
                'orden_trabajo': self.id,
                'shipment_out': remito.id,
            }])
            self.save()
            return True
        except:
            return False

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


class OrdenTrabajoStockShipmentOut(ModelSQL):
    'Orden Trabajo - Stock Shipment Out'
    __name__ = 'orden.trabajo-stock.shipment.out'
    _table = 'orden_trabajo_stock_shipment_out_rel'

    orden_trabajo = fields.Many2One('orden.trabajo', 'Orden Trabajo')
    shipment_out = fields.Many2One('stock.shipment.out', 'Shipment Out')


class Materiales(ModelSQL, ModelView):
    "Materiales para a orden de trabajo"
    __name__ = 'orden.trabajo.materiales'

    name = fields.Many2One('orden.trabajo', 'OT', ondelete='CASCADE')
    insumo = fields.Many2One('product.product', 'Insumo', required=True)
    cantidad = fields.Integer('Cantidad', required=True)
    usado = fields.Integer('Usado', states={'readonly':True})
    diferencia = fields.Function(fields.Integer('Diferencia'), 'get_diferencia')

    def get_diferencia(self, name):
        return self.cantidad - self.usado

    @staticmethod
    def default_usado():
        return 0


class CreateStockShipmentOutStart(ModelView):
    "Materiales para a orden de trabajo"
    __name__ = 'orden.trabajo.create_stock_shipment_out.start'

    materiales = fields.One2Many('orden.trabajo.materiales', None, 'OT')


class CreateStockShipmentOut(Wizard):
    'Create Stock Shipment Out'
    __name__ = 'orden.trabajo.create_stock_shipment_out'

    start = StateView('orden.trabajo.create_stock_shipment_out.start',
        'orden_trabajo.create_stock_shipment_out_start_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('Create', 'create_', 'tryton-ok', default=True),
            ])
    create_ = StateTransition()

    def transition_create_(self):
        ot_id = Transaction().context['active_id']
        orden_trabajo = Pool().get('orden.trabajo')(ot_id)
        if orden_trabajo.crear_remito():
            orden_trabajo
            return 'end'


class Workers(ModelSQL, ModelView):
    'Trabajdores de la Orden Trabajo'
    __name__ = 'orden.trabajo.workers'

    name = fields.Many2One('orden.trabajo', 'Orden Trabajo')
    party = fields.Many2One('party.party', 'Trabador')
    fecha_hora_inicio = fields.Timestamp('Hora Inicio')
    fecha_hora_fin = fields.Timestamp('Hora Fin')
    tiempo_trabajado = fields.TimeDelta('Horas Trabajadas')