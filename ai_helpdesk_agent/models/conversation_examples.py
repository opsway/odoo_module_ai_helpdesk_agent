import json
from odoo import models, fields
from odoo.exceptions import AccessError

class ConversationExamples(models.Model):
    _name = 'aihd.conversation_examples'
    _description = 'Conversation examples'
    _rec_name = 'subject'
    _order = 'id asc'

    ticket_id = fields.Many2one('helpdesk.ticket')
    subject = fields.Char()
    description = fields.Char()
    ticket_type_id = fields.Many2one('helpdesk.ticket.type')
    partner_id = fields.Many2one('res.partner')
    customer_name = fields.Char()
    customer_email = fields.Char()
    question = fields.Char()
    message_ids = fields.One2many('aihd.conversation_examples.message', 'example_id')
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published')], default='draft')
    active = fields.Boolean(default=True)
    set_readonly = fields.Boolean()

    def get_conv_examples(self):
        # TODO: not sure we need this method
        result = []
        exmpl_ids = self.with_context({'active_test': False}).search([])
        for exmpl_id in exmpl_ids:
            result.append({
                'ticket': {
                    'ticket_id': exmpl_id.ticket_id.id,
                    'subject': '',
                    'description': exmpl_id.description,
                    'ticket_type': exmpl_id.ticket_type_id.name,
                    'status': exmpl_id.state if exmpl_id.active else 'archived',
                    'last_update_at': str(exmpl_id.write_date.timestamp()).split('.')[0],
                    'customer_name': exmpl_id.customer_name,
                    'customer_email': exmpl_id.customer_email,
                    'messages': [{
                        'content': message.body,
                        'author': message.role,
                        'attachment_url': ''
                    } for message in exmpl_id.message_ids.sorted(lambda x: not x.sequence)]
                }
            })
        return json.dumps(result)

    def write(self, values):
        if len(values) == 1 and 'active' in values:
            return super(ConversationExamples, self).write(values)
        if len(values) == 1 and 'state' in values:
            return super(ConversationExamples, self).write(values)
        if self.state == 'published':
            raise AccessError("You can't edit published conversation")
        else:
            return super(ConversationExamples, self).write(values)

class ConversationExamplesMessage(models.Model):
    _name = 'aihd.conversation_examples.message'
    _description = 'Conversation examples message'
    _order = 'sequence desc,id'

    example_id = fields.Many2one('aihd.conversation_examples')
    body = fields.Text()
    role = fields.Selection([('user', 'User'), ('assistant', 'Assistant')])
    escalate = fields.Boolean()
    sequence = fields.Integer()

    # @api.onchange('escalate')
    # def _onchange_escalate(self):
    #     if self.escalate:
    #         self.body = 'ESCALATE'
