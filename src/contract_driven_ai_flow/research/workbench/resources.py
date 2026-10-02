"""Declarative resource intake is separate from probe binding and execution."""
from __future__ import annotations

import re
from jsonschema import Draft202012Validator, SchemaError
from .models import ProbeResource
from .store import WorkbenchStore


class ResourceManager:
    def __init__(self, root, catalog, tools=None):
        self.store = WorkbenchStore(root)
        self.catalog = catalog
        self.tools = tools
        for raw in self.store.list('resources', limit=1000):
            resource = ProbeResource.model_validate(raw)
            if resource.status == 'installed':
                self._activate(resource)

    def validate(self, resource):
        ids = set()
        for definition in resource.definitions:
            if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_.-]{0,127}', definition.id) or definition.id in ids:
                raise ValueError('Resource definition identities must be valid and unique')
            ids.add(definition.id)
            try:
                Draft202012Validator.check_schema(definition.parameter_schema)
            except SchemaError as error:
                raise ValueError('Invalid parameter schema') from error
            if definition.entrypoint and not re.fullmatch(r'[a-zA-Z_][\w.]*:[a-zA-Z_][\w.]*', definition.entrypoint):
                raise ValueError('Program entry must be module:qualified_symbol')
        return resource

    def import_manifest(self, raw):
        resource = self.validate(ProbeResource.model_validate(raw)).model_copy(deep=True, update={'status': 'draft'})
        for definition in resource.definitions:
            definition.resource_id = resource.id
        self.store.put('resources', resource.id, resource)
        return resource

    def _activate(self, resource):
        # Verify every collision before mutating the live registry.
        known = {definition.id: definition for definition in self.catalog.definitions()}
        for definition in resource.definitions:
            if definition.id in known and known[definition.id].resource_id != resource.id:
                raise ValueError('Resource cannot replace an existing probe definition')
        self.catalog.unregister_resource(resource.id)
        for definition in resource.definitions:
            self.catalog.register(definition.model_copy(deep=True, update={'resource_id': resource.id, 'resource_version': resource.version}))

    def enable(self, key):
        resource = self.validate(ProbeResource.model_validate(self.store.get('resources', key)))
        self._activate(resource)
        resource.status = 'installed'
        self.store.put('resources', key, resource)
        return resource

    def disable(self, key):
        resource = ProbeResource.model_validate(self.store.get('resources', key))
        self.catalog.unregister_resource(key)
        resource.status = 'disabled'
        self.store.put('resources', key, resource)
        return resource

    def resources(self):
        records = self.store.list('resources', limit=1000)
        builtin = [definition for definition in self.catalog.definitions() if not definition.resource_id and not definition.tool_id]
        records.append(ProbeResource(id='builtin', label='内置探针', version='3', source='builtin', status='installed', definitions=builtin).model_dump(mode='json'))
        if self.tools is not None:
            for tool in self.tools.catalog():
                records.append(ProbeResource(id='adapter.' + tool['id'], label=tool['label'], source='public', kind='adapter',
                    version=tool.get('version') or 'uninstalled', status='installed' if tool.get('available') and tool.get('enabled') else 'disabled' if tool.get('available') else 'available',
                    url=tool.get('url'), definitions=[definition for definition in self.catalog.definitions() if definition.tool_id == tool['id']]).model_dump(mode='json'))
        return records
