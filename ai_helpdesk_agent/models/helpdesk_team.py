import json
from odoo import models, fields, api


class HelpdeskTeam(models.Model):
    _inherit = 'helpdesk.team'

    mail_shortcode_ids = fields.Many2many('mail.shortcode')

    @api.model
    def get_templates(self):
        """Needs for API"""
        team_ids = self.search([])
        templates = []
        for team in team_ids:
            templates += [
                {
                    'id': canned.id,
                    'substitution': canned.substitution,
                } for canned in team.mail_shortcode_ids]
        return json.dumps(templates)