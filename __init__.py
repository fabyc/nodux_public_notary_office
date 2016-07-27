#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.
from trytond.pool import Pool
from .company import *
from .user import *
from .notary import *
from .party import *

def register():
    Pool.register(
        Company,
        User,
        Notary,
        Party,
        module='nodux_public_notary_office', type_='model')
    Pool.register(
        NotaryReport,
        module='nodux_public_notary_office', type_='report')
