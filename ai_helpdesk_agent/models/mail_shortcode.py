from odoo import models, fields


class MailShortcode(models.Model):
    _inherit = 'mail.shortcode'
    _rec_name = 'source'

    def get_canned_responses(self):
        # TODO: not sure we need this method
        result = []
        responses = self.search([])
        for response in responses:
            result.append(
                {
                    ''
                }
            )