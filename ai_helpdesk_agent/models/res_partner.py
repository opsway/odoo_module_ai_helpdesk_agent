from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ai_always_reply = fields.Boolean(
        help='For Helpdesk Ticket Customer',

    )