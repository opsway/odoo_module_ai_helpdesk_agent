# -*- coding: utf-8 -*-
from odoo import fields, models

class MailComposer(models.TransientModel):
    _inherit = 'mail.compose.message'

    message_type = fields.Selection(
        selection_add=[('auto_comment', 'Auto Comment')],
        ondelete={'auto_comment': 'set comment'},
    )

