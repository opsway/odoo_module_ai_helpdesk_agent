from odoo import models, api

class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        if self._name == 'helpdesk.ticket':
            custom_values = custom_values or {}
            custom_values.update({
                'can_process_by_ai': True
            })
        return super(MailThread, self).message_new(msg_dict, custom_values)
