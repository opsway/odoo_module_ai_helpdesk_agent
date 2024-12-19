# -*- coding: utf-8 -*-
import json
import random
import logging
import requests

from odoo import models, fields, api
from odoo.fields import Command

_logger = logging.getLogger(__name__)


def send_default_email(ticket_id):
    ticket_id.with_context(skip_auto_email=False)._message_track_post_template(['stage_id'])


def send_ai_response(ticket_id, ai_result, user_id):
    ticket_id.sudo().message_post(body=ai_result, message_type='comment', subtype_xmlid='mail.mt_comment',
                                  author_id=user_id.sudo().partner_id.id)

def get_ai_user(env):
    try:
        settings_val = int(env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.ai_user'))
        return env['res.users'].browse(settings_val)
    except (ValueError, TypeError):
        return env['res.users']


class HelpdeskTicket(models.Model):
    """
    :field can_process_by_ai: define triggers to set True for AI processing
    """
    _inherit = 'helpdesk.ticket'

    can_process_by_ai = fields.Boolean()
    auto_close_time = fields.Datetime()
    conv_exml_count = fields.Integer(compute='_compute_conv_exml_count')
    total_message_by_agent = fields.Integer(compute='_compute_total_message_by_agent')
    is_ai_redirected = fields.Boolean(compute='_compute_is_ai_redirected', store=True)

    def _compute_total_message_by_agent(self):
        for rec in self:
            ai_user = get_ai_user(self.env)
            rec.total_message_by_agent = bool(ai_user) and len(rec.message_ids.filtered(
                lambda x: x.author_id != ai_user and x.body)
            )

    @api.depends('user_id', 'tag_ids')
    def _compute_is_ai_redirected(self):
        for rec in self:
            ai_user = get_ai_user(self.env)
            rec.is_ai_redirected = (
                    bool(ai_user)
                    and ai_user != rec.user_id
                    and self.env.ref('ai_helpdesk_agent.tag_ai_reply') in rec.tag_ids
            )

    def _compute_conv_exml_count(self):
        self.conv_exml_count = len(self.env['aihd.conversation_examples'].search([('ticket_id', '=', self.id)]))

    def _message_post_after_hook(self, message, msg_vals):
        res = super()._message_post_after_hook(message, msg_vals)
        ticket_id = self
        ai_user = get_ai_user(self.env)
        is_assigned_to_ai = ai_user and ticket_id.user_id == ai_user
        is_customer_message = message.author_id and (message.author_id == ticket_id.partner_id)
        if is_assigned_to_ai and is_customer_message and message.body:
            ticket_id.with_delay(priority="1").process_ticket_by_ai(is_new=False)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        self = self.with_context(skip_auto_email=True)
        ticket_ids = super(HelpdeskTicket, self).create(vals_list)
        for ticket_id in ticket_ids:
            is_processed_by_ai = False
            process_on_creation = bool(int(self.env['ir.config_parameter'].sudo(
                ).get_param('ai_helpdesk_agent.Process_UI_Created_Tickets', 0)))
            if process_on_creation and not ticket_id.user_id:
                ticket_id.can_process_by_ai = True
            if ticket_id.can_process_by_ai:
                customer_flag = ticket_id.partner_id.ai_always_reply
                included_in_an_test = self.check_ab_test()
                if customer_flag or included_in_an_test:
                    ticket_id.with_delay(priority="1").process_ticket_by_ai(is_new=True)
                    is_processed_by_ai = True
            if not is_processed_by_ai:
                send_default_email(ticket_id)
        return ticket_ids

    def mass_process_tickets(self):
        for ticket in self:
            ticket.write({
                'tag_ids': False,
            })
            ticket.with_delay(priority="1").process_ticket_by_ai(is_new=True)

    def process_ticket_by_ai(self, is_new: bool):
        """
        param ticket_id: helpdesk.ticket
        param is_new: bool. If it isn't a new ticket then process as continue of conversation
        """
        self.ensure_one()
        try:
            ticket_id = self
            data = self.get_request_data(ticket_id)
            request = self.send_request(data)
            self.process_ai_response(ticket_id, request, continue_conv= not is_new)
        except Exception as err: # TODO: too wide, rollback/rerise error
            _logger.error(f'{ticket_id.id} AI Error, text: {err}')
            self.set_error_tag(ticket_id)

    @api.model
    def process_ai_response(self, ticket_id, request, continue_conv=False):
        dry_run = bool(int(self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.Dry_Run_Mode')))
        if dry_run and continue_conv or request.status_code != 200:
            self.set_error_tag(ticket_id)
            _logger.error(f'{ticket_id.id} AI Error, text: {request.text}, status: {request.status_code}')
            return
        request_data = request.json()
        text = request_data.get('text', '')
        escalate = request_data.get('actions', [])
        reasoning = request_data.get('reasoning', '')  # TODO: where to use it?
        self.save_ticket(ticket_id, escalate, continue_conv)
        ai_user_id = get_ai_user(self.env)
        if text:
            send_ai_response(ticket_id, text, ai_user_id)
        if reasoning:
            ticket_id.message_post(body=reasoning, message_type='comment', subtype_xmlid='mail.mt_note')

    @api.model
    def set_error_tag(self, ticket_id):
        err_tag_id = self.env.ref('ai_helpdesk_agent.tag_ai_error')
        ticket_id.write({
            'tag_ids': [Command.link(err_tag_id.id)],
        })
        self.change_user(ticket_id, after_error=True)
        send_default_email(ticket_id)

    @api.model
    def send_request(self, data):
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.api_key', '')
        api_ulr = self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.api_ulr', '')
        headers = {
            'Content-Type': 'application/json',
            'X-API-KEY': api_key,
        }
        request = requests.post(api_ulr, json=data, headers=headers, timeout=20)
        return request

    @api.model
    def save_ticket(self, ticket_id, escalate, continue_conv):
        try:
            if 'SKIP' in escalate:
                return
            ticket_id = ticket_id.with_context(skip_auto_email=False)
            tags = self.env['helpdesk.tag']
            if 'ESCALATE' in escalate:
                escalate_tag_id = self.env.ref('ai_helpdesk_agent.tag_ai_escalation')
                tags += escalate_tag_id
                team_id = ticket_id.team_id
                assign_to = team_id._determine_user_to_assign()[team_id.id]
            else:
                assign_to = get_ai_user(self.env)
            if continue_conv: # continue_conv is True if it's not a new ticket
                tags += self.env.ref('ai_helpdesk_agent.tag_ai_multi_turn')
            else:
                tags += self.env.ref('ai_helpdesk_agent.tag_ai_reply')
            ticket_id.write({
                    'tag_ids': [Command.link(tag.id) for tag in tags],
                    'user_id': assign_to.id,
                })
        except Exception as err: # TODO: too wide, rollback/rerise error
            _logger.error(err)

    def check_ab_test(self):
        try:
            ab_percent = int(self.env["ir.config_parameter"].sudo().get_param('ai_helpdesk_agent.ab_percent'), '')
        except (ValueError, TypeError):
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
            }) # TODO: why update? change to write?
        else:
            pass # TODO: add logic (here was "previous user" setting logic)

    def get_ticket_info(self):
        data = self.get_request_data(self)
        return json.dumps(data)

    def get_request_data(self, ticket_id, messages=[]):
        # TODO: Here was adding of attachment links
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
