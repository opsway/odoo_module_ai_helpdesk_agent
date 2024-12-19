{
    'name': 'AI Helpdesk Agent',
    'version': '16.0.0.1.0',
    'summary': 'Process tickets with AI and send responses to customers.',
    'description': 'AI for helpdesk tickets',
    'category': 'Services/Helpdesk',
    'author': 'OpsWay',
    'website': 'https://www.opsway.com/',
    'license': 'OPL-1',
    'depends': [
        'helpdesk',
        'base',
        'queue_job',
    ],
    'demo': [
        'data/demo/demo_data.xml',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_config_parameter.xml',
        'data/server_actions.xml',
        'views/res_config_settings.xml',
        'views/res_partner_view.xml',
        'views/helpdesk_team_view.xml',
        'views/helpdesk_ticket.xml',
        'views/conversation_examples_view.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False
}
