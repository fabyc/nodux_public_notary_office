#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
#! -*- coding: utf8 -*-
from trytond.pool import *
from trytond.model import fields
from trytond.pyson import Eval
from trytond.pyson import Id
import base64
__all__ = ['User']
__metaclass__ = PoolMeta


class User:
    __name__ = 'res.user'

    cabecera = fields.Selection([
                ('http', 'http://'),
                ('https', 'https://'),
            ], 'Protocolo de Comunicacion')

    puerto = fields.Char('Nro. Puerto', help="Puerto para conexion con WS-Nodux")
    direccion = fields.Char('Direccion del Servidor', help="Direccion para conexion con WS-Nodux")
    usuario = fields.Char('Usuario de la Base de Datos')
    name_db = fields.Char('Nombre de la Base de Datos')
    pass_db = fields.Char('Password de la Base de Datos')

    usuario_c = fields.Function(fields.Char('Usuario de la Base de Datos'), getter='get_user', setter='set_user')
    name_db_c = fields.Function(fields.Char('Nombre de la Base de Datos'), getter='get_name', setter='set_name')
    pass_db_c = fields.Function(fields.Char('Password de la Base de Datos'), getter='get_password_db', setter='set_password_db')

    @classmethod
    def __setup__(cls):
        super(User, cls).__setup__()

    @staticmethod
    def default_cabecera():
        return 'http'

    def get_password_db(self, name):
        return 'x' * 10

    @classmethod
    def set_password_db(cls, users, name, value):
        if value == 'x' * 10:
            return
        to_write = []
        for user in users:
            to_write.extend([[user], {
                        'pass_db': base64.encodestring(value),
                        }])
        cls.write(*to_write)

    def get_name(self, name):
        return 'x' * 10

    @classmethod
    def set_name(cls, users, name, value):
        if value == 'x' * 10:
            return
        to_write = []
        for user in users:
            to_write.extend([[user], {
                        'name_db': base64.encodestring(value),
                        }])
        cls.write(*to_write)

    def get_user(self, name):
        return 'x' * 10

    @classmethod
    def set_user(cls, users, name, value):
        if value == 'x' * 10:
            return
        to_write = []
        for user in users:
            to_write.extend([[user], {
                        'usuario': base64.encodestring(value),
                        }])
        cls.write(*to_write)
