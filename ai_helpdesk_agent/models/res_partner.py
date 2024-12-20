from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ai_always_reply = fields.Boolean(
        help='For Helpdesk Ticket Customer',

    ) # TODO: set True by default for all portal users for Demo Mode?