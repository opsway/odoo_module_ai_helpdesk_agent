from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    helpdesk_ai_user_id = fields.Many2one(
        'res.users',
        domain=[('share', '=', False)],
        config_parameter='ai_helpdesk_agent.ai_user'
    )