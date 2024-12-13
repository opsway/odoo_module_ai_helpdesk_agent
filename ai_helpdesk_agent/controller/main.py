import json

from odoo import http, _
from odoo.http import request

import logging

_logger = logging.getLogger(__name__)


class Main(http.Controller):
    # TODO: not sure we need this

    @http.route(['/ticket-info/<int:ticket_id>'], type='http', auth="api_key", methods=['GET'], csrf=False)
    def get_ticket_data(self, ticket_id, **kwargs):
        _logger.error(ticket_id)
        ticket_id = request.env['helpdesk.ticket'].browse(ticket_id)
        data = request.env['helpdesk.ticket'].get_request_data(ticket_id)
        return json.dumps(data)
