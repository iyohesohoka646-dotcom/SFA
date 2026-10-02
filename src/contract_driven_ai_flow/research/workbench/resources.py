"""Declarative resource intake is separate from probe binding and execution."""
from __future__ import annotations

import re
import hashlib
from pathlib import Path
from jsonschema import Draft202012Validator, SchemaError
from .models import ProbeResource
from .store import WorkbenchStore


class ResourceManager:
    def __init__(self, root, catalog, tools=None):
        self.root=Path(root).resolve()
        self.store = WorkbenchStore(root)
        self.catalog = catalog
        self.tools = tools
        for raw in self.store.list('resources', limit=1000):
            resource = ProbeResource.model_validate(raw)
            if resource.status == 'installed':
                try:self._activate(resource)
                except ValueError as error:
                    resource.status='error';resource.diagnostics=[str(error)]
                    self.store.put('resources',resource.id,resource)

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
        try:active=ProbeResource.model_validate(self.store.get('resources',resource.id))
        except KeyError:active=None
        self.store.put('resource_drafts' if active and active.status=='installed' else 'resources', resource.id, resource)
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
        try:raw=self.store.get('resource_drafts',key)
        except KeyError:raw=self.store.get('resources',key)
        resource = self.validate(ProbeResource.model_validate(raw))
        for definition in resource.definitions:
            if definition.entrypoint:
                module=definition.entrypoint.split(':')[0]
                path=self.root.joinpath(*module.split('.')).with_suffix('.py')
                if path.is_file():definition.implementation_digest=hashlib.sha256(path.read_bytes()).hexdigest()
        self._activate(resource)
        resource.status = 'installed'
        self.store.put('resources', key, resource)
        self.store.delete('resource_drafts',key)
        return resource

    def disable(self, key):
        resource = ProbeResource.model_validate(self.store.get('resources', key))
        self.catalog.unregister_resource(key)
        resource.status = 'disabled'
        self.store.put('resources', key, resource)
        return resource

    def resources(self):
        records = self.store.list('resources', limit=1000)
        drafts={r['id']:r for r in self.store.list('resource_drafts',limit=1000)}
        for record in records:
            if record['id'] in drafts:record['pending_version']=drafts[record['id']]['version']
        builtin = [definition for definition in self.catalog.definitions() if not definition.resource_id and not definition.tool_id]
        records.append(ProbeResource(id='builtin', label='内置探针', version='3', source='builtin', status='installed', definitions=builtin).model_dump(mode='json'))
        if self.tools is not None:
            for tool in self.tools.catalog():
                records.append(ProbeResource(id='adapter.' + tool['id'], label=tool['label'], source='public', kind='adapter',
                    version=tool.get('version') or 'uninstalled', status='installed' if tool.get('available') and tool.get('enabled') else 'disabled' if tool.get('available') else 'available',
                    url=tool.get('url'), definitions=[definition for definition in self.catalog.definitions() if definition.tool_id == tool['id']]).model_dump(mode='json'))
        return records
