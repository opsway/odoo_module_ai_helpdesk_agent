from odoo import models, api
from odoo.tools.misc import clean_context

class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    def _message_track_post_template(self, changes):
        # TODO where is super call?
        """ Based on a tracking, post a message defined by ``_track_template``
        parameters. It allows to implement automatic post of messages based
        on templates (e.g. stage change triggering automatic email).

        :param dict changes: mapping {record_id: (changed_field_names, tracking_value_ids)}
            containing existing records only
        """
        if not changes or self._context.get('skip_auto_email', False):
            return True
        # Clean the context to get rid of residual default_* keys
        # that could cause issues afterward during the mail.message
        # generation. Example: 'default_parent_id' would refer to
        # the parent_id of the current record that was used during
        # its creation, but could refer to wrong parent message id,
        # leading to a traceback in case the related message_id
        # doesn't exist
        self = self.with_context(clean_context(self._context))
        templates = self._track_template(changes)
        for _field_name, (template, post_kwargs) in templates.items():
            if not template:
                continue
            # defaults to automated notifications targeting customer
            # whose answers should be considered as comments
            post_kwargs.setdefault('message_type', 'comment') # TODO: it was 'auto_comment' instead of 'comment'
            if isinstance(template, str):
                self._fallback_lang().message_post_with_view(template, **post_kwargs)
            else:
                self._fallback_lang().message_post_with_template(template.id, **post_kwargs)
        return True

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        # when User create ticket by emailing
        """Called by ``message_process`` when a new message is received
           for a given thread model, if the message did not belong to
           an existing thread.
           The default behavior is to create a new record of the corresponding
           model (based on some very basic info extracted from the message).
           Additional behavior may be implemented by overriding this method.

           :param dict msg_dict: a map containing the email details and
                                 attachments. See ``message_process`` and
                                ``mail.message.parse`` for details.
           :param dict custom_values: optional dictionary of additional
                                      field values to pass to create()
                                      when creating the new thread record.
                                      Be careful, these values may override
                                      any other values coming from the message.
           :rtype: int
           :return: the id of the newly created thread object
        """
        # TODO where is super call?
        data = {}
        if isinstance(custom_values, dict):
            data = custom_values.copy()
        model_fields = self.fields_get()
        name_field = self._rec_name or 'name'
        if name_field in model_fields and not data.get('name'):
            data[name_field] = msg_dict.get('subject', '')

        primary_email = self._mail_get_primary_email_field()
        if primary_email and msg_dict.get('email_from'):
            data[primary_email] = msg_dict['email_from']
        if self._name == 'helpdesk.ticket':
            data.update({
                'can_process_by_ai': True
            })

        return self.create(data)


class MailMessage(models.Model):
    _inherit = 'mail.message'

    def process_by_ai(self):
        pass # TODO del
