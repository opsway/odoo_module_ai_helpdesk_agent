import json
from odoo import models, fields


class HelpdeskTeam(models.Model):
    _inherit = 'helpdesk.team'

    mail_shortcode_ids = fields.Many2many('mail.shortcode')

    def get_templates(self):
        #  TODO: not sure we need this method
        team_ids = self.search([])
        templates = []
        for team in team_ids:
            templates += [
                {
                    'id': canned.id,
                    'substitution': canned.substitution,
                } for canned in team.mail_shortcode_ids]
        return json.dumps(templates)


class MailShortcode(models.Model):
    _inherit = 'mail.shortcode'
    _rec_name = 'source'