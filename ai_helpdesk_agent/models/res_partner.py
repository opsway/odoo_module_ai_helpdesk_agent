from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ai_always_reply = fields.Boolean() #  TODO: set it True by default for all portal users? For Demo only?
    #  TODO: set it Trueo on ticket creation. if ticket is created by mail new partner is created