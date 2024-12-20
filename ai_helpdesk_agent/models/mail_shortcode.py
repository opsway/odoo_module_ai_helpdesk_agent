from odoo import models


class MailShortcode(models.Model):
    _inherit = 'mail.shortcode'
    _rec_name = 'source'

    def get_canned_responses(self):
        """Needs for API""" # TODO is not complete
        result = []
        responses = self.search([])
        for response in responses:
            result.append(
                {
                    ''
                }
            )