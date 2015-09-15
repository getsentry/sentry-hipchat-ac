# -*- coding: utf-8 -*-
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'Tenant'
        db.create_table(u'sentry_hipchat_tenant', (
            ('id', self.gf('django.db.models.fields.CharField')(max_length=40, primary_key=True)),
            ('room_id', self.gf('django.db.models.fields.CharField')(max_length=40)),
            ('secret', self.gf('django.db.models.fields.CharField')(max_length=120)),
            ('homepage', self.gf('django.db.models.fields.CharField')(max_length=250)),
            ('token_url', self.gf('django.db.models.fields.CharField')(max_length=250)),
            ('capabilities_url', self.gf('django.db.models.fields.CharField')(max_length=250)),
            ('api_base_url', self.gf('django.db.models.fields.CharField')(max_length=250)),
            ('installed_from', self.gf('django.db.models.fields.CharField')(max_length=250)),
        ))
        db.send_create_signal(u'sentry_hipchat', ['Tenant'])


    def backwards(self, orm):
        # Deleting model 'Tenant'
        db.delete_table(u'sentry_hipchat_tenant')


    models = {
        u'sentry_hipchat.tenant': {
            'Meta': {'object_name': 'Tenant'},
            'api_base_url': ('django.db.models.fields.CharField', [], {'max_length': '250'}),
            'capabilities_url': ('django.db.models.fields.CharField', [], {'max_length': '250'}),
            'homepage': ('django.db.models.fields.CharField', [], {'max_length': '250'}),
            'id': ('django.db.models.fields.CharField', [], {'max_length': '40', 'primary_key': 'True'}),
            'installed_from': ('django.db.models.fields.CharField', [], {'max_length': '250'}),
            'room_id': ('django.db.models.fields.CharField', [], {'max_length': '40'}),
            'secret': ('django.db.models.fields.CharField', [], {'max_length': '120'}),
            'token_url': ('django.db.models.fields.CharField', [], {'max_length': '250'})
        }
    }

    complete_apps = ['sentry_hipchat']
