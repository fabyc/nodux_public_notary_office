# -*- coding: utf-8 -*-

# This file is part of sale_pos module for Tryton.
# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
from decimal import Decimal
import datetime
from trytond.model import ModelSQL, Workflow, fields, ModelView
from trytond.pool import PoolMeta, Pool
from trytond.transaction import Transaction
from trytond.pyson import Bool, Eval, Or, If
from trytond.wizard import (Wizard, StateView, StateAction, StateTransition,
    Button)
from trytond.modules.company import CompanyReport
from trytond.report import Report
from lxml import etree
import base64
import xmlrpclib
import re
from xml.dom.minidom import parse, parseString
import time
from trytond.rpc import RPC
import os
from trytond.config import config
import re

directory = config.get('database', 'path')
directory_xml = directory +'/factura.xml'

__all__ = ['Notary', 'NotaryReport']

_STATES = {
    'readonly': Eval('state') != 'draft',
}
_DEPENDS = ['state']

_TYPE = [
    ('out_invoice', 'Invoice'),
    ('out_credit_note', 'Credit Note'),
]

class Notary(Workflow, ModelSQL, ModelView):
    'Notary'
    __name__ = 'notary.notary'
    _order_name = 'invoice_date'

    company = fields.Many2One('company.company', 'Company', required=True,
        readonly=True, select=True, domain=[
            ('id', If(Eval('context', {}).contains('company'), '=', '!='),
                Eval('context', {}).get('company', -1)),
            ],
        depends=_DEPENDS)
    party = fields.Many2One('party.party', 'Party', readonly=True)
    number_invoice = fields.Char('No. Comprobante', readonly=True)
    subtotal = fields.Numeric('Subtotal', readonly=True)
    iva = fields.Numeric('IVA', readonly=True)
    total = fields.Numeric('Total', readonly=True)
    archivo_xml = fields.Binary('Factura formato XML', help="Cargar el archivo xml para firma y autorizacion", states=_STATES)
    state = fields.Selection([
            ('draft', 'Draft'),
            ('send', 'Send'),
            ], 'State', readonly=True)

    type = fields.Selection(_TYPE, 'Type', select=True,
        required=True, states=_STATES, depends=_DEPENDS)
    mensaje = fields.Text('Mensaje de error SRI', readonly=True, states={
            'invisible': Eval('estado_sri') != 'NO AUTORIZADO',
            })
    estado_sri = fields.Char('Estado Facturacion-Electronica', size=24, readonly=True)
    path_xml = fields.Char(u'Path archivo xml de comprobante', readonly=True)
    path_pdf = fields.Char(u'Path archivo pdf de factura', readonly=True)
    numero_autorizacion = fields.Char('Numero Autorizacion', readonly=True)
    clave = fields.Char('Clave de acceso', readonly=True)
    invoice_date = fields.Char('Fecha', readonly=True)
    fecha_autorizacion = fields.Char('Fecha Autorizacion', readonly=True)
    matrizador = fields.Char('Matrizador', readonly=True)
    no_libro = fields.Char('Numero de libro', readonly=True)

    @classmethod
    def __setup__(cls):
        super(Notary, cls).__setup__()
        cls._order.insert(1, ('invoice_date', 'DESC'))
        cls._order.insert(0, ('id', 'DESC'))
        cls._error_messages.update({
                'modify_notary': ('You can not modify invoice "%s" because '
                    'it is send.'),
                'delete_notary': ('You can not delete invoice "%s" because '
                    'it is send.'),
                })

        cls._buttons.update({
                'draft': {
                    'invisible': Eval('state') != 'send'
                },
                'send': {
                    'invisible': Eval('state') != 'draft'
                },
            })

    @staticmethod
    def default_state():
        return 'draft'

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @fields.depends('archivo_xml', 'type')
    def on_change_archivo_xml(self):
        res= {}
        if self.archivo_xml:
            f = open(directory_xml, 'wb')
            f.write(self.archivo_xml)
            f.close()
            doc=etree.parse(directory_xml)
            raiz=doc.getroot()
            infoComprobante = raiz[1]
            if self.type == 'out_invoice':
                if infoComprobante.tag == 'infoFactura':
                    print "infoComprobante", infoComprobante.tag, infoComprobante.text
                    pass
                else:
                    res['archivo_xml'] = None
            if self.type == 'out_credit_note':
                if infoComprobante.tag == 'infoNotaCredito':
                    pass
                else:
                    res['archivo_xml'] = None
            os.remove(directory_xml)
        return res

    @classmethod
    def check_modify(cls, notaries):
        for notary in notaries:
            if (notary.state in ('send')):
                cls.raise_user_error('modify_notary', (notary.number_invoice,))

    @classmethod
    def delete(cls, notaries):
        cls.check_modify(notaries)
        for notary in notaries:
            if (notary.state in ('send')):
                cls.raise_user_error('delete_notary', (notary.number_invoice,))
        super(Notary, cls).delete(notaries)

    def replace_charter(self, cadena):
        reemplazo = {u"Â":"A", u"Á":"A", u"À":"A", u"Ä":"A", u"É":"E", u"È":"E", u"Ê":"E",u"Ë":"E",
            u"Í":"I",u"Ì":"I",u"Î":"I",u"Ï":"I",u"Ó":"O",u"Ò":"O",u"Ö":"O",u"Ô":"O",u"Ú":"U",u"Ù":"U",u"Ü":"U",
            u"Û":"U",u"á":"a",u"à":"a",u"â":"a",u"ä":"a",u"é":"e",u"è":"e",u"ê":"e",u"ë":"e",u"í":"i",u"ì":"i",
            u"ï":"i",u"î":"i",u"ó":"o",u"ò":"o",u"ô":"o",u"ö":"o",u"ú":"u",u"ù":"u",u"ü":"u",u"û":"u",u"ñ":"n",
            u"Ñ":"N"}
        regex = re.compile("(%s)" % "|".join(map(re.escape, reemplazo.keys())))
        nueva_cadena = regex.sub(lambda x: str(reemplazo[x.string[x.start():x.end()]]), cadena)
        return nueva_cadena

    def web_service(self):
        CONEXION = 'UD NO HA CONFIGURADO LOS DATOS DE CONEXION CON EL WS, \nCOMUNIQUESE CON EL ADMINISTRADOR DEL SISTEMA'
        pool = Pool()
        conexions = pool.get('res.user')
        conexion = conexions.search([('id', '=', 1)])
        if conexion:
            for c in conexion:
                if c.direccion:
                    address = c.cabecera+"://"+base64.decodestring(c.usuario)+":"+base64.decodestring(c.pass_db)+"@"+c.direccion+":"+c.puerto+"/"+base64.decodestring(c.name_db)
                    return address
                else:
                    self.raise_user_error(CONEXION)

    def send_mail_invoice(self, xml_element, access_key, send_m, s, server="localhost"):
        MAIL= u"Ud no ha configurado el correo del cliente. Diríjase a: \nTerceros->General->Medios de Contacto"
        pool = Pool()
        empresa = self.replace_charter(self.company.party.name) #cambiado por self.elimina_tildes(self.company.party.name)
        empresa = empresa.replace(' ','_')
        empresa = empresa.lower()
        ahora = datetime.datetime.now()
        year = str(ahora.year)
        client = self.replace_charter(self.party.name) #reemplazo self.party.name
        client = client.upper()
        empresa_ = self.replace_charter(self.company.party.name) #reemplazo self.company.party.name
        ruc = self.company.party.vat_number
        if ahora.month < 10:
            month = '0'+ str(ahora.month)
        else:
            month = str(ahora.month)

        tipo_comprobante = self.type
        if tipo_comprobante == 'out_invoice':
            tipo = 'fact_'
            n_tipo = "FACTURA"
        if tipo_comprobante == 'out_credit_note':
            tipo = 'n_c_'
            n_tipo = "NOTA DE CREDITO"

        ruc = access_key[10:23]
        est = access_key[24:27]
        emi= access_key[27:30]
        sec = access_key[30:39]
        num_fac = est+'-'+emi+'-'+sec
        numero = ruc+'_'+num_fac
        name_pdf = tipo+numero+ '.pdf'
        name_xml = tipo+numero + '.xml'
        #nuevaruta =os.getcwd() +'/comprobantes/'+empresa+'/'+year+'/'+month +'/'
        nr = s.model.nodux_electronic_invoice_auth.conexiones.path_files(ruc, {})
        nuevaruta = nr +empresa+'/'+year+'/'+month +'/'

        new_save = 'comprobantes/'+empresa+'/'+year+'/'+month +'/'
        self.write([self],{'path_xml': new_save+name_xml,'path_pdf':new_save+name_pdf})

        correos = pool.get('party.contact_mechanism')
        correo = correos.search([('type','=','email')])

        Report = Pool().get('notary.notary', type='report')
        report = Report.execute([self.id], {})

        email=''
        cont = 0
        for c in correo:
            if c.party == self.party:
                email = c.value
            if c.party == self.company.party:
                cont = cont +1
                f_e = c.value

        if email != '':
            to_email= email
        else :
            self.raise_user_error(MAIL)

        if send_m == '1':
            from_email = f_e
        else :
            from_email = "nodux.ec@gmail.com"
        name = access_key + ".xml"
        reporte = xmlrpclib.Binary(report[1])
        xml_element = self.replace_charter(xml_element)
        #xml_element = unicode(xml_element, 'utf-8')
        xml = xmlrpclib.Binary(xml_element.replace('><', '>\n<'))
        #reporte = xmlrpclib.Binary(xml_element.replace('><', '>\n<'))

        save_files = s.model.nodux_electronic_invoice_auth.conexiones.save_file(empresa, name_pdf, name_xml, reporte, xml,{})
        p_xml = nuevaruta + name_xml
        p_pdf = nuevaruta + name_pdf
        s.model.nodux_electronic_invoice_auth.conexiones.send_mail(name_pdf, name, p_xml, p_pdf, from_email, to_email, n_tipo, num_fac, client, empresa_, ruc, {})
        return True

    def connect_db(self):

        address_xml = self.web_service()
        s= xmlrpclib.ServerProxy(address_xml)

        pool = Pool()
        nombre = self.party.name
        cedula = self.party.vat_number
        ruc = self.company.party.vat_number
        nombre_e = self.company.party.name
        tipo = self.type
        fecha = str(self.invoice_date)
        empresa = self.company.party.name
        numero = self.number_invoice
        path_xml = self.path_xml
        path_pdf = self.path_pdf
        estado = self.estado_sri
        auth = self.clave
        correos = pool.get('party.contact_mechanism')
        correo = correos.search([('type','=','email')])
        for c in correo:
            if c.party == self.party:
                to_email = c.value
            if c.party == self.company.party:
                to_email_2 = c.value
        email_e= to_email_2
        email = to_email
        total = str(self.total)

        if self.estado_sri == 'AUTORIZADO':
            s.model.nodux_electronic_invoice_auth.conexiones.connect_db( nombre, cedula, ruc, nombre_e, tipo, fecha, empresa, numero, path_xml, path_pdf,estado, auth, email, email_e, total, {})

    def action_generate_invoice(self):
        PK12 = u'No ha configurado los datos de la empresa. Dirijase a: \n Empresa -> NODUX WS'
        AUTHENTICATE_ERROR = u'Error de datos de conexión al autorizador de \nfacturacion electrónica.\nVerifique: USUARIO Y CONTRASEÑA .'
        ACTIVE_ERROR = u"Ud. no se encuentra activo, verifique su pago. \nComuníquese con NODUX"
        WAIT_FOR_RECEIPT = 3
        TITLE_NOT_SENT = u'No se puede enviar el comprobante electronico al SRI'
        MESSAGE_SEQUENCIAL = u'Los comprobantes electrónicos deben ser enviados al SRI en orden secuencial'
        MESSAGE_TIME_LIMIT = u'Se ha excedido el límite de tiempo. Los comprobantes electrónicos deben ser enviados al SRI para su autorización, en un plazo máximo de 24 horas'
        WAIT_FOR_RECEIPT = 15
        pool = Pool()
        Notary = pool.get('notary.notary')
        usuario = self.company.user_ws
        password_u= self.company.password_ws
        #access_key = self.generate_access_key()
        address_xml = self.web_service()
        s= xmlrpclib.ServerProxy(address_xml)
        if self.archivo_xml:
            pass
        else:
            self.raise_user_error('No ha ingresado el archivo XML para ser firmado y enviado al SRI')
        if self.type == 'out_invoice':
            f = open(directory_xml, 'wb')
            f.write(self.archivo_xml)
            f.close()
            doc=etree.parse(directory_xml)
            raiz=doc.getroot()

            infoComprobante = raiz[1]
            if infoComprobante.tag == 'infoFactura':
                pass
            else:
                self.raise_user_error('El archivo ingresado no corresponde a una factura')

            name = self.company.party.name
            name_l=name.lower()
            name_l=name_l.replace(' ','_')
            name_r = self.replace_charter(name_l)
            name_c = name_r+'.p12'

            authenticate, send_m, active = s.model.nodux_electronic_invoice_auth.conexiones.authenticate(usuario, password_u, {})
            if authenticate == '1':
                pass
            else:
                self.raise_user_error(AUTHENTICATE_ERROR)

            if active == '1':
                self.raise_user_error(ACTIVE_ERROR)
            else:
                pass

            nuevaruta = s.model.nodux_electronic_invoice_auth.conexiones.save_pk12(name_l, {})
            factura = etree.tostring(doc, encoding = 'utf8', method = 'xml')
            factura = self.replace_charter(str(factura))
            file_pk12 = base64.encodestring(nuevaruta+'/'+name_c)
            file_check = (nuevaruta+'/'+name_c)
            password = self.company.password_pk12
            error = s.model.nodux_electronic_invoice_auth.conexiones.check_digital_signature(file_check,{})
            if error == '1':
                self.raise_user_error('No se ha encontrado el archivo de firma digital (.p12)')


            signed_document= s.model.nodux_electronic_invoice_auth.conexiones.apply_digital_signature(factura, file_pk12, password,{})
            #signed_document = self.replace_charter(signed_document)
            #envio al sri para recepcion del comprobante electronico
            result = s.model.nodux_electronic_invoice_auth.conexiones.send_receipt(signed_document, {})
            if result != True:
                self.raise_user_error(result)
            time.sleep(WAIT_FOR_RECEIPT)
            # solicitud al SRI para autorizacion del comprobante electronico
            if self.company.party.email:
                email = self.company.party.email
            else:
                self.raise_user_error('No ha configurado el correo de la empresa')

            numero_factura = ""
            totalSinImpuestos = Decimal(0.0)
            importeTotal = Decimal(0.0)
            nombre = ""
            numero_libro = ""
            matrizador = ""
            direccion = "Loja"
            phone = ""
            mobile = ""

            if len(raiz) == 3:
                infoTributaria = raiz[0]
                infoFactura = raiz[1]
                detalles = raiz[2]
                infoAdicional = None
            if len(raiz) == 4 :
                infoTributaria = raiz[0]
                infoFactura = raiz[1]
                detalles = raiz[2]
                infoAdicional = raiz[3]

            for it in infoTributaria:
                if it.tag == "claveAcceso":
                    access_key = it.text
                if it.tag == "estab":
                    estab = it.text
                if it.tag == "ptoEmi":
                    ptoEmi = it.text
                if it.tag == "secuencial":
                    secuencial = it.text
            numero_factura = str(estab)+'-'+str(ptoEmi)+'-'+secuencial
            notaries = Notary.search([('number_invoice', '=', numero_factura)])
            if notaries :
                self.raise_user_error('Comprobante ya enviado al SRI')

            for i_f in infoFactura:
                if i_f.tag == "identificacionComprador":
                    vat_number = i_f.text
                if i_f.tag == 'razonSocialComprador':
                    nombre = i_f.text
                if i_f.tag == 'direccionComprador':
                    direccion = i_f.text
                if i_f.tag == 'totalSinImpuestos':
                    totalSinImpuestos = Decimal(i_f.text)
                if i_f.tag == 'importeTotal':
                    importeTotal = Decimal(i_f.text)
                if i_f.tag == 'fechaEmision':
                    fechaEmision = i_f.text

            if infoAdicional != None:
                for ia in infoAdicional:
                    if re.match("[a-zA-ZñÑáéíóúÁÉÍÓÚ\ ]", ia.text):
                        matrizador = ia.text
                        break

            if infoAdicional != None:
                for ia in infoAdicional:
                    if re.match("[a-z0-9]", ia.text):
                        numero_libro = ia.text
                        break

            if infoAdicional != None:
                for ia in infoAdicional:
                    if re.match("[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,3})", ia.text):
                        email = ia.text
                        break

            if infoAdicional != None:
                for ia in infoAdicional:
                    if ia.text.isdigit() and len(ia.text) > 9:
                        mobile = ia.text
                        break

            if infoAdicional != None:
                for ia in infoAdicional:
                    if ia.text.isdigit() and len(ia.text) <=9:
                        phone = ia.text
                        break
            doc_xml, m, auth, path, numero, num = s.model.nodux_electronic_invoice_auth.conexiones.request_authorization(access_key, name_r, 'out_invoice', signed_document,{})

            if doc_xml is None:
                msg = ' '.join(m)
                raise m

            if auth == 'NO AUTORIZADO':
                Party = pool.get('party.party')
                parties = Party.search([('vat_number', '=', vat_number)])
                if parties:
                    for p in parties:
                        party = p
                else:
                    correo =  email
                    Contact = pool.get('party.contact_mechanism')
                    Address = pool.get('party.address')
                    party = Party()
                    party.name = nombre
                    party.vat_number = vat_number
                    party.save()
                    contact_mechanisms = []
                    contact_mechanisms.append({
                            'type':'email',
                            'value':correo,
                            'party':party.id
                    })
                    if phone != "":
                        contact_mechanisms.append({
                                'type':'phone',
                                'value':phone,
                                'party':party.id,
                        })
                    if mobile != "":
                        contact_mechanisms.append({
                                'type':'mobile',
                                'value':mobile,
                                'party':party.id,
                        })
                    party.address = Address.create([{
                            'street': direccion,
                            'party':party.id
                    }])
                    contact_mechanisms = Contact.create(contact_mechanisms)

                    party.save()

                self.write([self],{
                        'party': party.id,
                        'number_invoice':numero_factura,
                        'subtotal':totalSinImpuestos,
                        'iva': Decimal(importeTotal-totalSinImpuestos),
                        'total': importeTotal,
                        'estado_sri':'NO AUTORIZADO',
                        'numero_autorizacion':num,
                        'clave':access_key,
                        'invoice_date':str(fechaEmision),
                        'mensaje':doc_xml,
                        'no_libro':numero_libro,
                        'matrizador':matrizador})
            else:
                Party = pool.get('party.party')
                parties = Party.search([('vat_number', '=', vat_number)])
                if parties:
                    for p in parties:
                        party = p
                else:
                    correo =  email
                    Contact = pool.get('party.contact_mechanism')
                    Address = pool.get('party.address')
                    party = Party()
                    party.name = nombre
                    party.vat_number = vat_number
                    party.save()
                    contact_mechanisms = []
                    contact_mechanisms.append({
                            'type':'email',
                            'value':correo,
                            'party':party.id
                    })
                    if phone != "":
                        contact_mechanisms.append({
                                'type':'phone',
                                'value':phone,
                                'party':party.id,
                        })
                    if mobile != "":
                        contact_mechanisms.append({
                                'type':'mobile',
                                'value':mobile,
                                'party':party.id,
                        })
                    party.address = Address.create([{
                            'street': direccion,
                            'party':party.id
                    }])
                    contact_mechanisms = Contact.create(contact_mechanisms)
                    party.save()

                self.write([self],{
                        'party': party.id,
                        'number_invoice':numero_factura,
                        'subtotal':totalSinImpuestos,
                        'iva': Decimal(importeTotal-totalSinImpuestos),
                        'total': importeTotal,
                        'estado_sri':'AUTORIZADO',
                        'numero_autorizacion':num,
                        'clave':access_key,
                        'invoice_date':str(fechaEmision),
                        'no_libro':numero_libro,
                        'matrizador':matrizador})
                self.send_mail_invoice(doc_xml, access_key, send_m, s)

            os.remove(directory_xml)

        else:
            if self.type == 'out_credit_note':
                f = open(directory_xml, 'wb')
                f.write(self.archivo_xml)
                f.close()
                doc=etree.parse(directory_xml)
                raiz=doc.getroot()

                infoComprobante = raiz[1]
                if infoComprobante.tag == 'infoNotaCredito':
                    pass
                else:
                    self.raise_user_error('El archivo ingresado no corresponde a Nota de Credito')

                name = self.company.party.name
                name_l=name.lower()
                name_l=name_l.replace(' ','_')
                name_r = self.replace_charter(name_l)
                name_c = name_r+'.p12'

                authenticate, send_m, active = s.model.nodux_electronic_invoice_auth.conexiones.authenticate(usuario, password_u, {})

                if authenticate == '1':
                    pass
                else:
                    self.raise_user_error(AUTHENTICATE_ERROR)

                if active == '1':
                    self.raise_user_error(ACTIVE_ERROR)
                else:
                    pass

                nuevaruta = s.model.nodux_electronic_invoice_auth.conexiones.save_pk12(name_l, {})

                # XML del comprobante electronico: nota de credito
                notaCredito = etree.tostring(doc, encoding = 'utf8', method = 'xml')
                file_pk12 = base64.encodestring(nuevaruta+'/'+name_c)
                file_check = (nuevaruta+'/'+name_c)
                password = self.company.password_pk12
                error = s.model.nodux_electronic_invoice_auth.conexiones.check_digital_signature(file_check,{})
                if error == '1':
                    self.raise_user_error('No se ha encontrado el archivo de firma digital (.p12)')
                signed_document = s.model.nodux_electronic_invoice_auth.conexiones.apply_digital_signature(notaCredito, file_pk12, password,{})
                #signed_document = self.replace_charter(signed_document)
                #envio al sri para recepcion del comprobante electronico
                result = s.model.nodux_electronic_invoice_auth.conexiones.send_receipt(signed_document, {})

                if result != True:
                    self.raise_user_error(result)
                time.sleep(WAIT_FOR_RECEIPT)
                # solicitud al SRI para autorizacion del comprobante electronico
                if self.company.party.email:
                    email = self.company.party.email
                else:
                    self.raise_user_error('No ha configurado el correo de la empresa')

                numero_factura = ""
                totalSinImpuestos = Decimal(0.0)
                importeTotal = Decimal(0.0)
                nombre = ""
                direccion = "Loja"
                phone = ""
                mobile = ""
                if len(raiz) == 3:
                    infoTributaria = raiz[0]
                    infoNotaCredito = raiz[1]
                    detalles = raiz[2]
                    infoAdicional = None
                if len(raiz) == 4 :
                    infoTributaria = raiz[0]
                    infoNotaCredito = raiz[1]
                    detalles = raiz[2]
                    infoAdicional = raiz[3]

                for it in infoTributaria:
                    if it.tag == "claveAcceso":
                        access_key = it.text
                    if it.tag == "estab":
                        estab = it.text
                    if it.tag == "ptoEmi":
                        ptoEmi = it.text
                    if it.tag == "secuencial":
                        secuencial = it.text
                numero_factura = str(estab)+'-'+str(ptoEmi)+'-'+secuencial
                notaries = Notary.search([('number_invoice', '=', numero_factura)])
                if notaries :
                    self.raise_user_error('Comprobante ya enviado al SRI')

                for i_f in infoNotaCredito:
                    if i_f.tag == "identificacionComprador":
                        vat_number = i_f.text
                    if i_f.tag == 'razonSocialComprador':
                        nombre = i_f.text
                    if i_f.tag == 'direccionComprador':
                        direccion = i_f.text
                    if i_f.tag == 'totalSinImpuestos':
                        totalSinImpuestos = Decimal(i_f.text)
                    if i_f.tag == 'valorModificacion':
                        importeTotal = Decimal(i_f.text)
                    if i_f.tag == 'fechaEmision':
                        fechaEmision = i_f.text

                if infoAdicional != None:
                    for ia in infoAdicional:
                        if re.match("[a-zA-ZñÑáéíóúÁÉÍÓÚ\ ]", ia.text):
                            matrizador = ia.text
                            break

                if infoAdicional != None:
                    for ia in infoAdicional:
                        if re.match("[a-z0-9]", ia.text):
                            numero_libro = ia.text
                            break

                if infoAdicional != None:
                    for ia in infoAdicional:
                        if re.match("[_a-z0-9-]+(\.[_a-z0-9-]+)*@[a-z0-9-]+(\.[a-z0-9-]+)*(\.[a-z]{2,3})", ia.text):
                            email = ia.text
                            break

                if infoAdicional != None:
                    for ia in infoAdicional:
                        if ia.text.isdigit() and len(ia.text) > 9:
                            mobile = ia.text
                            break

                if infoAdicional != None:
                    for ia in infoAdicional:
                        if ia.text.isdigit() and len(ia.text) <=9:
                            phone = ia.text
                            break

                doc_xml, m, auth, path, numero, num = s.model.nodux_electronic_invoice_auth.conexiones.request_authorization(access_key, name_r, 'out_credit_note', signed_document, {})
                if doc_xml is None:
                    msg = ' '.join(m)
                    raise m

                if auth == 'NO AUTORIZADO':
                    Party = pool.get('party.party')
                    parties = Party.search([('vat_number', '=', vat_number)])
                    if parties:
                        for p in parties:
                            party = p
                    else:
                        correo =  email
                        Contact = pool.get('party.contact_mechanism')
                        Address = pool.get('party.address')
                        party = Party()
                        party.name = nombre
                        party.vat_number = vat_number
                        party.save()
                        contact_mechanisms = []
                        contact_mechanisms.append({
                                'type':'email',
                                'value':correo,
                                'party':party.id
                        })
                        if phone != "":
                            contact_mechanisms.append({
                                    'type':'phone',
                                    'value':phone,
                                    'party':party.id,
                            })
                        if mobile != "":
                            contact_mechanisms.append({
                                    'type':'mobile',
                                    'value':mobile,
                                    'party':party.id,
                            })
                        party.address = Address.create([{
                                'street': direccion,
                                'party':party.id
                        }])
                        contact_mechanisms = Contact.create(contact_mechanisms)

                        party.save()

                    self.write([self],{
                            'party': party.id,
                            'number_invoice':numero_factura,
                            'subtotal':totalSinImpuestos,
                            'iva': Decimal(importeTotal-totalSinImpuestos),
                            'total': importeTotal,
                            'estado_sri':'NO AUTORIZADO',
                            'numero_autorizacion':num,
                            'clave':access_key,
                            'invoice_date':str(fechaEmision),
                            'mensaje':doc_xml,
                            'state':'draft',
                            'no_libro':numero_libro,
                            'matrizador':matrizador})
                else:
                    Party = pool.get('party.party')
                    parties = Party.search([('vat_number', '=', vat_number)])
                    if parties:
                        for p in parties:
                            party = p
                    else:
                        correo =  email
                        Contact = pool.get('party.contact_mechanism')
                        Address = pool.get('party.address')
                        party = Party()
                        party.name = nombre
                        party.vat_number = vat_number
                        party.save()
                        contact_mechanisms = []
                        contact_mechanisms.append({
                                'type':'email',
                                'value':correo,
                                'party':party.id
                        })
                        if phone != "":
                            contact_mechanisms.append({
                                    'type':'phone',
                                    'value':phone,
                                    'party':party.id,
                            })
                        if mobile != "":
                            contact_mechanisms.append({
                                    'type':'mobile',
                                    'value':mobile,
                                    'party':party.id,
                            })
                        party.address = Address.create([{
                                'street': direccion,
                                'party':party.id
                        }])
                        contact_mechanisms = Contact.create(contact_mechanisms)

                        party.save()

                    self.write([self],{
                            'party': party.id,
                            'number_invoice':numero_factura,
                            'subtotal':totalSinImpuestos,
                            'iva': Decimal(importeTotal-totalSinImpuestos),
                            'total': importeTotal,
                            'estado_sri':'AUTORIZADO',
                            'numero_autorizacion':num,
                            'clave':access_key,
                            'invoice_date':str(fechaEmision),
                            'no_libro':numero_libro,
                            'matrizador':matrizador})

                    self.send_mail_invoice(doc_xml, access_key, send_m, s)
                os.remove(directory_xml)
        return access_key

    @classmethod
    @ModelView.button
    def send(cls, notaries):
        for notary in notaries:
            notary.action_generate_invoice()
            notary.connect_db()

        cls.write([i for i in notaries if (i.state != 'sent' and i.estado_sri == "AUTORIZADO")], {
                'state': 'send',
                })

class NotaryReport(Report):
    __name__ = 'notary.notary'

    @classmethod
    def __setup__(cls):
        super(NotaryReport, cls).__setup__()
        cls.__rpc__['execute'] = RPC(False)

    @classmethod
    def execute(cls, ids, data):
        Notary = Pool().get('notary.notary')

        res = super(NotaryReport, cls).execute(ids, data)
        if len(ids) > 1:
            res = (res[0], res[1], True, res[3])
        else:
            notary = Notary(ids[0])
            if notary.number_invoice:
                res = (res[0], res[1], res[2], res[3] + ' - ' + notary.number_invoice)
        return res

    @classmethod
    def _get_records(cls, ids, model, data):
        with Transaction().set_context(language=False):
            return super(NotaryReport, cls)._get_records(ids[:1], model, data)

    @classmethod
    def parse(cls, report, records, data, localcontext):
        pool = Pool()
        User = pool.get('res.user')
        Notayr = pool.get('notary.notary')

        notary = records[0]

        user = User(Transaction().user)
        localcontext['company'] = user.company
        localcontext['barcode_img']=cls._get_barcode_img(Notary, notary)
        localcontext['lines'] = cls._get_lines(Notary, notary)
        localcontext['subtotal0'] = cls._get_subtotal_0(Notary, notary)
        localcontext['subtotal14'] = cls._get_subtotal_14(Notary, notary)
        if notary.type == 'out_credit_note':
            localcontext['numero'] = cls._get_numero(Notary, notary)
            localcontext['fecha'] = cls._get_fecha(Notary, notary)
            localcontext['motivo'] = cls._get_motivo(Notary, notary)

        return super(NotaryReport, cls).parse(report, records, data,
                localcontext=localcontext)

    @classmethod
    def _get_lines(cls, Notary, notary):
        f = open(directory_xml, 'wb')
        f.write(notary.archivo_xml)
        f.close()
        doc=etree.parse(directory_xml)
        lines = {}
        raiz=doc.getroot()
        infoTributaria = raiz[0]
        infoFactura = raiz[1]
        detalles = raiz[2]
        lineas = {}
        invoice_lines = []
        cod= ""
        descripcion =""
        cantidad =""
        precioUnitario = ""
        descuento = ""
        precioTotalSinImpuesto = ""
        impuestos = ""
        for detalle in detalles:
            lineas = {}
            for d in detalle:
                if d.tag == "codigoPrincipal":
                    cod= d.text
                if d.tag == "descripcion":
                    descripcion = d.text
                if d.tag == "cantidad":
                    cantidad = d.text
                if d.tag == "precioUnitario":
                    precioUnitario = d.text
                if d.tag == "descuento":
                    descuento = d.text
                if d.tag == "precioTotalSinImpuesto":
                    precioTotalSinImpuesto = d.text
                if d.tag == "impuestos":
                    impuestos = d.text
                lineas['cod'] = cod
                lineas['descripcion'] = descripcion
                lineas['cantidad'] = cantidad
                lineas['precioUnitario'] = precioUnitario
                lineas['descuento'] = descuento
                lineas['precioTotalSinImpuesto'] = precioTotalSinImpuesto
                lineas['impuestos'] = impuestos
            invoice_lines.append(lineas)
        os.remove(directory_xml)
        return invoice_lines

    @classmethod
    def _get_barcode_img(cls, Notary, notary):
        from barras import CodigoBarra
        from cStringIO import StringIO as StringIO
        # create the helper:
        codigobarra = CodigoBarra()
        output = StringIO()
        bars= notary.clave
        codigobarra.GenerarImagen(bars, output, basewidth=3, width=380, height=50, extension="PNG")
        image = buffer(output.getvalue())
        output.close()
        return image

    @classmethod
    def _get_subtotal_0(cls, Notary, notary):
        subtotal0 = Decimal(0.00)
        f = open(directory_xml, 'wb')
        f.write(notary.archivo_xml)
        f.close()
        doc=etree.parse(directory_xml)
        lines = {}
        raiz=doc.getroot()
        infoTributaria = raiz[0]
        infoFactura = raiz[1]
        detalles = raiz[2]

        for info in infoFactura:
            for impuestos in info:
                a = False
                for i in impuestos:
                    if i.tag == "codigoPorcentaje" and i.text == "0":
                        a = True
                    if a == True:
                        if i.tag == "baseImponible":
                            subtotal0 += Decimal(i.text)

        return subtotal0

    @classmethod
    def _get_subtotal_14(cls, Notary, notary):
        subtotal14 = Decimal(0.00)
        f = open(directory_xml, 'wb')
        f.write(notary.archivo_xml)
        f.close()
        doc=etree.parse(directory_xml)
        lines = {}
        raiz=doc.getroot()
        infoTributaria = raiz[0]
        infoFactura = raiz[1]
        detalles = raiz[2]

        for info in infoFactura:
            for impuestos in info:
                a = False
                for i in impuestos:
                    if i.tag == "codigoPorcentaje" and i.text == "3":
                        a = True
                    if a == True:
                        if i.tag == "baseImponible":
                            subtotal14 += Decimal(i.text)
        return subtotal14

    @classmethod
    def _get_numero(cls, Notary, notary):
        f = open(directory_xml, 'wb')
        f.write(notary.archivo_xml)
        f.close()
        doc=etree.parse(directory_xml)
        raiz=doc.getroot()
        infoNotaCredito = raiz[1]
        numero= ""
        for inc in infoNotaCredito:
            if inc.tag == "numDocModificado":
                numero = inc.text
        os.remove(directory_xml)
        return numero

    @classmethod
    def _get_fecha(cls, Notary, notary):
        f = open(directory_xml, 'wb')
        f.write(notary.archivo_xml)
        f.close()
        doc=etree.parse(directory_xml)
        raiz=doc.getroot()
        infoNotaCredito = raiz[1]
        fecha= ""
        for inc in infoNotaCredito:
            if inc.tag == "fechaEmisionDocSustento":
                fecha = inc.text
        os.remove(directory_xml)
        return fecha

    @classmethod
    def _get_motivo(cls, Notary, notary):
        f = open(directory_xml, 'wb')
        f.write(notary.archivo_xml)
        f.close()
        doc=etree.parse(directory_xml)
        raiz=doc.getroot()
        infoNotaCredito = raiz[1]
        motivo = "Emitir factura con el mismo concepto"
        for inc in infoNotaCredito:
            if inc.tag == "motivo":
                motivo = inc.text
        os.remove(directory_xml)
        return motivo
