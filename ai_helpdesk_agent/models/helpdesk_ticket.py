# -*- coding: utf-8 -*-
import json
import random
import logging
import requests

from datetime import datetime
from dateutil.relativedelta import relativedelta

from odoo import models, fields, api
from odoo.fields import Command

_logger = logging.getLogger(__name__)


def send_default_email(ticket_id):
    ticket_id.with_context(skip_auto_email=False)._message_track_post_template(['stage_id'])


def send_ai_response(ticket_id, ai_result, user_id):
    ticket_id.sudo().message_post(body=ai_result, message_type='comment', subtype_xmlid='mail.mt_comment',
                                  author_id=user_id.sudo().partner_id.id)


class HelpdeskTicket(models.Model):
    """
    :field can_process_by_ai: define triggers to set True for AI processing
    """
    _inherit = 'helpdesk.ticket'

    can_process_by_ai = fields.Boolean(default=True) #  TODO: remove it
    auto_close_time = fields.Datetime()
    conv_exml_count = fields.Integer(compute='_compute_conv_exml_count')
    total_message_by_agent = fields.Integer(compute='_compute_total_message_by_agent')

    def _compute_total_message_by_agent(self):
        for rec in self:
            rec.total_message_by_agent = len(rec.message_ids.filtered(
                lambda x: x.author_id.name != 'AI Agent' and x.body)
            )

    def _compute_conv_exml_count(self):
        self.conv_exml_count = len(self.env['aihd.conversation_examples'].search([('ticket_id', '=', self.id)]))

    @api.model_create_multi
    def create(self, vals_list):
        self = self.with_context(skip_auto_email=True)
        ticket_id = super(HelpdeskTicket, self).create(vals_list)
        process_on_creation = bool(int(self.env['ir.config_parameter'].sudo(
            ).get_param('ai_helpdesk_agent.Process_UI_Created_Tickets', 0)))
        if process_on_creation and not ticket_id.user_id:
            ticket_id.can_process_by_ai = True
        if ticket_id.can_process_by_ai:
            customer_flag = ticket_id.partner_id.ai_always_reply
            included_in_an_test = self.check_ab_test()
            if customer_flag or included_in_an_test:
                self.with_delay(priority="1").process_new_ticket(ticket_id)
            else:
                send_default_email(ticket_id)
        else:
            send_default_email(ticket_id)
        return ticket_id

    def process_new_ticket(self, ticket_id):
        try:
            data = self.get_request_data(ticket_id)
            request = self.send_request(data)
            self.process_request(ticket_id, request)

        except Exception as err:
            _logger.error(f'{ticket_id.id} AI Error, text: {err}')
            self.set_error_tag(ticket_id, 'AI Error', False)

    def process_request(self, ticket_id, request, continue_conv=False):
        dry_run = bool(int(self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.Dry_Run_Mode')))
        if request.status_code == 200:
            if not dry_run:
                request_data = request.json()
                text = request_data.get('text', '')
                escalate = request_data.get('actions', [])
                reasoning = request_data.get('reasoning', '') #  TODO: where to use it?
                self.save_ticket(ticket_id, escalate, continue_conv)
                if text:
                    ai_user_id = self.env['res.users'].search([('name', '=', 'AI Agent')], limit=1)
                    send_ai_response(ticket_id, text, ai_user_id)
            else:
                if continue_conv:
                    self.set_error_tag(ticket_id, 'AI Error', continue_conv)
                    _logger.error(f'{ticket_id.id} AI Error, text: {request.text}, status: {request.status_code}')
                else:
                    send_default_email(ticket_id)
            return
        else:
            self.set_error_tag(ticket_id, 'AI Error', continue_conv)
            _logger.error(f'{ticket_id.id} AI Error, text: {request.text}, status: {request.status_code}')

    def set_error_tag(self, ticket_id, tag_name, continue_conv=False):
        tag_id = self.env['helpdesk.tag'].search([('name', '=', tag_name)])
        if continue_conv:
            self.change_user(ticket_id, after_error=True)
        else:
            send_default_email(ticket_id)
        ticket_id.write({
            'tag_ids': [Command.link(tag_id.id)],
        })

    def send_request(self, data):
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.api_key', '')
        api_ulr = self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.api_ulr')
        headers = {
            'Content-Type': 'application/json',
            'X-API-KEY': api_key,
        }
        request = requests.post(api_ulr, json=data, headers=headers, timeout=20)
        return request

    def save_ticket(self, ticket_id, escalate, continue_conv):
        try:
            ticket_id = ticket_id.with_context(skip_auto_email=False)
            ai_reply_tag_id = self.env['helpdesk.tag'].search([('name', '=', 'AI Reply')], limit=1)
            multi_tag_id = self.env['helpdesk.tag'].search([('name', '=', 'AI Multi-Turn')], limit=1)
            team_id = ticket_id.team_id
            escalate_tag_id = False
            if 'ESCALATE' in escalate:
                escalate_tag_id = self.env['helpdesk.tag'].search([('name', '=', 'AI Escalation')])
            data = {}
            ai_user_id = self.env['res.users'].search([('name', '=', 'AI Agent')], limit=1)
            if continue_conv:
                tags = [Command.link(multi_tag_id.id)]
                if escalate_tag_id:
                    tags += [Command.link(escalate_tag_id.id)]
                data.update({
                    'tag_ids': tags,
                    'user_id': ai_user_id.id,
                })
            else:
                tags = [Command.link(ai_reply_tag_id.id)]
                if escalate_tag_id:
                    tags += [Command.link(escalate_tag_id.id)]
                    assigned = team_id._determine_user_to_assign()[team_id.id]
                else:
                    assigned = ai_user_id
                data.update({
                    'tag_ids':tags,
                    'user_id': assigned.id,

                })
            ticket_id.write(data)
        except Exception as err:
            _logger.error(err)

    def auto_close_tickit(self):
        ticket_ids = self.search([('auto_close_time', '<=', datetime.now())])
        for ticket_id in ticket_ids:
            if ticket_id.stage_id.name == 'Waiting to client':
                stage_id = self.env['helpdesk.stage'].search([('name', '=', 'Resolved')])
                ticket_id.write({
                    'stage_id': stage_id.id,
                    'auto_close_time': False
                })

    def check_ab_test(self):
        try:
            ab_percent = int(self.env["ir.config_parameter"].sudo().get_param('ai_helpdesk_agent.ab_percent'))
        except Exception:
            ab_percent = 0
        random_number = random.randint(1, 100)
        if random_number <= ab_percent:
            return True
        else:
            return False

    def change_user(self, ticket_id, after_error=False):
        if after_error:
            team_id = ticket_id.team_id
            ticket_id.update({
                'user_id': team_id._determine_user_to_assign()[team_id.id].id
            })
        else:
            pass #  TODO: add logic (here was "previous user" setting logic)

    def get_ticket_info(self):
        data = self.get_request_data(self)
        return json.dumps(data)

    def get_request_data(self, ticket_id, messages=[]):
        #  TODO: Here was adding of attachment links
        data = {
            'ticket': {
                'ticket_id': ticket_id.id,
                'subject': ticket_id.name if ticket_id.name else '',
                'description': str(ticket_id.description) if ticket_id.description else '',
                'ticket_type': ticket_id.ticket_type_id.name if ticket_id.ticket_type_id.name else '',
                'customer_name': ticket_id.partner_id.name if ticket_id.partner_id.name else '',
                'customer_email': ticket_id.partner_id.email if ticket_id.partner_id.email else '',
                'question': '',
                'messages': messages,
            },
        }
        return data

    def action_conv_expl(self):
        dialog_id = self.env['aihd.conversation_examples'].create([{
            'ticket_id': self.id,
            'subject': self.name,
            'description': str(self.description),
            'ticket_type_id': self.ticket_type_id.id,
            'partner_id': self.partner_id.id,
            'customer_name': self.partner_id.name,
            'customer_email': self.partner_id.email,
            'message_ids': [(0, 0, {
                'body': message.body,
                'role': 'user' if self.partner_id.id == message.author_id.id else 'assistant',
            }) for message in self.message_ids.filtered(lambda x: x.body and x.author_id.id not in [2, 36])]
        }])
        self._compute_conv_exml_count()
        return {
            'name': 'Dialog',
            'view_mode': 'form',
            'res_model': 'aihd.conversation_examples',
            'type': 'ir.actions.act_window',
            'res_id': dialog_id.id,
            'target': 'current',
        }

    def action_open_helpdesk_conv_exml(self):
        return {
            'name': 'Conversation Example',
            'view_mode': 'tree,form',
            'res_model': 'aihd.conversation_examples',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', self.env['aihd.conversation_examples'].search([('ticket_id', '=', self.id)]).ids)],
            'target': 'current',
        }
