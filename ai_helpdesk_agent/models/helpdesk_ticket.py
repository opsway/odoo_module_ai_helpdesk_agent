# -*- coding: utf-8 -*-
import json
import random
import logging
import requests

from odoo import models, fields, api
from odoo.fields import Command

from ..const import AIActions

_logger = logging.getLogger(__name__)


def send_default_email(ticket_id):
    ticket_id.with_context(skip_auto_email=False)._message_track_post_template(['stage_id'])


def send_ai_response(ticket_id, ai_result, user_id):
    ticket_id.sudo().message_post(body=ai_result, message_type='comment', subtype_xmlid='mail.mt_comment',
                                  author_id=user_id.sudo().partner_id.id)

def get_ai_user(env):
    try:
        settings_val = int(env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.ai_user', 0))
        return env['res.users'].browse(settings_val)
    except (ValueError, TypeError):
        return env['res.users']


class HelpdeskTicket(models.Model):
    _inherit = 'helpdesk.ticket'

    can_process_by_ai = fields.Boolean()
    conv_exml_count = fields.Integer(compute='_compute_conv_exml_count')
    total_message_by_agent = fields.Integer(compute='_compute_total_message_by_agent')
    is_ai_redirected = fields.Boolean(compute='_compute_is_ai_redirected', store=True)

    def get_ticket_info(self):
        """Needs for API"""
        data = self._get_request_data()
        return json.dumps(data)

    def _mass_process_tickets(self):
        for ticket in self:
            ticket.write({
                'tag_ids': False,
            })
            ticket.with_delay(priority="1")._process_ticket_by_ai(is_new=True)

    def _process_ticket_by_ai(self, is_new: bool):
        """ Main method to process ticket by AI
        param is_new: bool In case it isn't a new ticket, then process as continue of conversation
        """
        self.ensure_one()
        data = self._get_request_data()
        request = self._send_request(data)
        self._process_ai_response(request, continue_conv=not is_new)

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
        """AI replies to Customer's messages. Odoo core hook"""
        res = super()._message_post_after_hook(message, msg_vals)
        ai_user = get_ai_user(self.env)
        is_assigned_to_ai = ai_user and self.user_id == ai_user
        is_customer_message = message.author_id and (message.author_id == self.partner_id)
        if is_assigned_to_ai and is_customer_message and message.body:
            self.with_delay(priority="1")._process_ticket_by_ai(is_new=False)
        return res

    @api.model_create_multi
    def create(self, vals_list):
        self = self.with_context(skip_auto_email=True)
        ticket_ids = super(HelpdeskTicket, self).create(vals_list)
        for ticket_id in ticket_ids:
            is_processed_by_ai = False
            ticket_id._mark_can_process_by_ai()
            if ticket_id.can_process_by_ai:
                customer_flag = ticket_id.partner_id.ai_always_reply
                included_in_an_test = self._check_ab_test()
                if customer_flag or included_in_an_test:
                    ticket_id.with_delay(priority="1")._process_ticket_by_ai(is_new=True)
                    is_processed_by_ai = True
            if not is_processed_by_ai:
                send_default_email(ticket_id)
        return ticket_ids

    def _mark_can_process_by_ai(self):
        """For cases when ticket creates without an assigned user, mostly through UI"""
        try:
            process_on_creation = bool(int(self.env['ir.config_parameter'].sudo(
            ).get_param('ai_helpdesk_agent.Process_UI_Created_Tickets', 0)))
        except (ValueError, TypeError):
            process_on_creation = False
        for ticket_id in self:
            if process_on_creation and not ticket_id.user_id:
                ticket_id.can_process_by_ai = True

    def _process_ai_response(self, request, continue_conv):
        dry_run = bool(int(self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.Dry_Run_Mode', 0)))
        if dry_run and continue_conv or request.status_code != 200:
            self._set_error_tag()
            _logger.error(f'{self.id} AI Error, text: {request.text}, status: {request.status_code}')
            return
        request_data = request.json()
        text = request_data.get('text', '')
        escalate = request_data.get('actions', [])
        reasoning = request_data.get('reasoning', '')
        self._save_ticket(escalate, continue_conv)
        ai_user_id = get_ai_user(self.env)
        if text:
            send_ai_response(self, text, ai_user_id)
        if reasoning:
            self.message_post(body=reasoning, message_type='comment', subtype_xmlid='mail.mt_note')

    def _save_ticket(self, escalate, continue_conv):
        self.ensure_one()
        self = self.with_context(skip_auto_email=False)
        tags = self.env['helpdesk.tag']
        if AIActions.ESCALATE in escalate:
            escalate_tag_id = self.env.ref('ai_helpdesk_agent.tag_ai_escalation')
            tags += escalate_tag_id
            team_id = self.team_id
            assign_to = team_id._determine_user_to_assign()[team_id.id]
        else:
            assign_to = get_ai_user(self.env)
        if continue_conv: # continue_conv is True if it's not a new ticket
            tags += self.env.ref('ai_helpdesk_agent.tag_ai_multi_turn')
        else:
            tags += self.env.ref('ai_helpdesk_agent.tag_ai_reply')
        self.write({
                'tag_ids': [Command.link(tag.id) for tag in tags],
                'user_id': assign_to.id,
            })

    @api.model
    def _set_error_tag(self):
        err_tag_id = self.env.ref('ai_helpdesk_agent.tag_ai_error')
        self.write({
            'tag_ids': [Command.link(err_tag_id.id)],
        })
        self._change_user()
        send_default_email(self)

    @api.model
    def _send_request(self, data):
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.api_key', '')
        api_ulr = self.env['ir.config_parameter'].sudo().get_param('ai_helpdesk_agent.api_ulr', '')
        headers = {
            'Content-Type': 'application/json',
            'X-API-KEY': api_key,
        }
        request = requests.post(api_ulr, json=data, headers=headers, timeout=20)
        return request

    @api.model
    def _check_ab_test(self):
        try:
            ab_percent = int(self.env["ir.config_parameter"].sudo().get_param('ai_helpdesk_agent.ab_percent', 0))
        except (ValueError, TypeError):
            ab_percent = 0
        random_number = random.randint(1, 100)
        if random_number <= ab_percent:
            return True
        else:
            return False

    def _change_user(self):
        self.ensure_one()
        team_id = self.team_id
        self.write({
            'user_id': team_id._determine_user_to_assign()[team_id.id].id
        })

    def _get_request_data(self, messages=[]):
        # TODO: Add attachments from messages?
        self.ensure_one()
        data = {
            'ticket': {
                'ticket_id': self.id,
                'subject': self.name if self.name else '',
                'description': str(self.description) if self.description else '',
                'ticket_type': self.ticket_type_id.name if self.ticket_type_id.name else '',
                'customer_name': self.partner_id.name if self.partner_id.name else '',
                'customer_email': self.partner_id.email if self.partner_id.email else '',
                'question': '',
                'messages': messages,
            },
        }
        return data

    def _action_conv_expl(self):
        self.ensure_one()
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
        """button, it must be a public method"""
        self.ensure_one()
        return {
            'name': 'Conversation Example',
            'view_mode': 'tree,form',
            'res_model': 'aihd.conversation_examples',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', self.env['aihd.conversation_examples'].search([('ticket_id', '=', self.id)]).ids)],
            'target': 'current',
        }
