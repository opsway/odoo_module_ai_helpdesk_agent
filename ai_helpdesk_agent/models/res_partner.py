from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    ai_always_reply = fields.Boolean() # TODO: set it True by default for all portal users? For Demo only?