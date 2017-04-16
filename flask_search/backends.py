#!/usr/bin/env python
# -*- coding: utf-8 -*-
# **************************************************************************
# Copyright © 2017 jianglin
# File Name: backends.py
# Author: jianglin
# Email: xiyang0807@gmail.com
# Created: 2017-04-15 20:03:27 (CST)
# Last Update:星期日 2017-4-16 13:45:30 (CST)
#          By:
# Description:
# **************************************************************************
import logging
import os
import os.path
import sys

from sqlalchemy.inspection import inspect
from sqlalchemy.types import (Boolean, Date, DateTime, Float, Integer, String,
                              Text)
from whoosh import index as whoosh_index
from whoosh.analysis import StemmingAnalyzer
from whoosh.fields import (ID, BOOLEAN, DATETIME, IDLIST, KEYWORD, NGRAM,
                           NGRAMWORDS, NUMERIC, TEXT, Schema)
from whoosh.qparser import AndGroup, MultifieldParser, OrGroup

DEFAULT_WHOOSH_INDEX_NAME = 'whoosh_index'
DEFAULT_ANALYZER = StemmingAnalyzer()
DEFAULT_PRIMARY_KEY = 'id'

log_console = logging.StreamHandler(sys.stderr)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_console)


class Search(object):
    def __init__(self, app=None, analyzer=None):
        self.whoosh_path = DEFAULT_WHOOSH_INDEX_NAME
        self._indexs = {}
        self.analyzer = analyzer or DEFAULT_ANALYZER
        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        self.app = app
        whoosh_name = app.config.get('WHOOSH_BASE')
        if whoosh_name is not None:
            self.whoosh_path = whoosh_name
        if not os.path.exists(self.whoosh_path):
            os.mkdir(whoosh_name)
        # ix=index.create_in(whoosh_name,schema)

    def create_one_index(self,
                         instance,
                         writer=None,
                         update=False,
                         delete=False,
                         commit=True):
        if update and delete:
            raise ValueError("update and delete can't work togther")
        ix = self._index(instance.__class__)
        searchable = ix.schema.names()
        if not writer:
            writer = ix.writer()
        attrs = {'id': str(instance.id)}
        for i in searchable:
            attrs[i] = str(getattr(instance, i))
        if delete:
            logger.debug('deleting index: {}'.format(instance))
            writer.delete_by_term('id', str(instance.id))
        elif update:
            logger.debug('updating index: {}'.format(instance))
            writer.update_document(**attrs)
        else:
            logger.debug('creating index: {}'.format(instance))
            writer.add_document(**attrs)
        if commit:
            writer.commit()
        return instance

    def create_index(self, model='__all__', update=False, delete=False):
        if model == '__all__':
            return self.create_all_index(update, delete)
        ix = self._index(model)
        writer = ix.writer()
        instances = model.query.enable_eagerloads(False).yield_per(100)
        for instance in instances:
            self.create_one_index(instance, writer, update, delete, False)
        writer.commit()
        return ix

    def create_all_index(self, update=False, delete=False):
        all_models = self.app.extensions[
            'sqlalchemy'].db.Model._decl_class_registry.values()
        models = [i for i in all_models if hasattr(i, '__searchable__')]
        ixs = []
        for m in models:
            ix = self.create_index(m, update, delete)
            ixs.append(ix)
        return ixs

    def _index(self, model):
        '''
        get index
        '''
        name = model.__table__.name
        if name not in self._indexs:
            ix_path = os.path.join(self.whoosh_path, name)
            if whoosh_index.exists_in(ix_path):
                ix = whoosh_index.open_dir(ix_path)
            else:
                if not os.path.exists(ix_path):
                    os.makedirs(ix_path)
                schema = self._schema(model)
                ix = whoosh_index.create_in(ix_path, schema)
            self._indexs[name] = ix
        return self._indexs[name]

    def _schema(self, model):
        schema_fields = {'id': ID(stored=False, unique=True)}
        searchable = set(model.__searchable__)
        primary_keys = [key.name for key in inspect(model).primary_key]
        for field in searchable:
            field_type = getattr(model, field).property.columns[0].type
            if field in primary_keys:
                schema_fields[field] = ID(stored=True, unique=True)
            elif field_type in (DateTime, Date):
                schema_fields[field] = DATETIME(stored=True, sortable=True)
            elif field_type == Integer:
                schema_fields[field] = NUMERIC(stored=True, numtype=int)
            elif field_type == Float:
                schema_fields[field] = NUMERIC(stored=True, numtype=float)
            elif field_type == Boolean:
                schema_fields[field] = BOOLEAN(stored=True)
            else:
                schema_fields[field] = TEXT(
                    stored=True, analyzer=self.analyzer, sortable=True)

        return Schema(**schema_fields)

    def whoosh_search(self, m, query, fields=None, limit=None, or_=False):
        ix = self._index(m)
        if fields is None:
            fields = ix.schema.names()
        group = OrGroup if or_ else AndGroup
        parser = MultifieldParser(fields, ix.schema, group=group)
        results = ix.searcher().search(parser.parse(query), limit=limit)
        # if not results:
        # return self.filter(sqlalchemy.text('null'))
        # results = ix.searcher().search_page(parser.parse(query), 1, pagelen=10)
        return results