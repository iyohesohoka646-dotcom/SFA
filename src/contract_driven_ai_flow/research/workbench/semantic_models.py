"""Display semantics and target contracts; never a source-read permission graph."""
from __future__ import annotations

from typing import Literal
from pydantic import Field, model_validator
from ..models import SourceRef, WireModel

TargetKind = Literal['data', 'operation', 'function', 'control', 'file', 'project', 'folder', 'stream']


class TargetRef(WireModel):
    kind: TargetKind = 'data'
    logical_key: str
    object_id: str | None = None
    block_id: str | None = None
    analysis_id: str | None = None
    run_id: str | None = None
    snapshot_id: str | None = None


class ScopeSelector(WireModel):
    mode: Literal['selection', 'block', 'project'] = 'project'
    block_id: str | None = None
    targets: list[TargetRef] = Field(default_factory=list)
    excluded_keys: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def require_block(self):
        if self.mode == 'block' and not self.block_id:
            raise ValueError('Block scope requires a block identity')
        return self


class GraphPort(WireModel):
    id: str
    name: str
    direction: Literal['input', 'output']


class GraphBlock(WireModel):
    id: str
    logical_key: str
    kind: Literal['file', 'function', 'class', 'condition', 'loop', 'try', 'with', 'folder', 'project', 'stream']
    label: str
    parent_id: str | None = None
    source: SourceRef | None = None
    source_object_id: str | None = None
    members: list[str] = Field(default_factory=list)
    runtime_coverage: Literal['supported', 'partial', 'unsupported'] = 'supported'


class GraphNode(WireModel):
    id: str
    kind: Literal['operation', 'data', 'parameter', 'condition', 'loop_header', 'merge', 'return', 'call', 'entry', 'exit', 'unknown']
    label: str
    block_id: str
    logical_key: str = ''
    source: SourceRef | None = None
    source_object_id: str | None = None
    ports: list[GraphPort] = Field(default_factory=list)
    version: int = 1


class GraphEdge(WireModel):
    id: str
    source: str
    target: str
    kind: Literal['data', 'control', 'call', 'argument', 'return', 'merge', 'backedge', 'contains', 'block']
    label: str = ''
    source_port: str | None = None
    target_port: str | None = None
    branch: Literal['true', 'false', 'body', 'exit', 'exception'] | None = None
    provenance: Literal['inferred', 'declared', 'observed', 'unknown'] = 'inferred'
    original_ids: list[str] = Field(default_factory=list)
    count: int = 1


class GraphCoverage(WireModel):
    code: str
    message: str
    source: SourceRef | None = None
    runtime: Literal['supported', 'partial', 'unsupported'] = 'partial'


class SemanticGraph(WireModel):
    protocol_version: Literal[3] = 3
    source_digest: str = ''
    roots: list[str] = Field(default_factory=list)
    blocks: list[GraphBlock] = Field(default_factory=list)
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    coverage: list[GraphCoverage] = Field(default_factory=list)
    omitted_count: int = 0

    @model_validator(mode='after')
    def check_references(self):
        ids = [item.id for item in [*self.blocks, *self.nodes]]
        known = set(ids)
        if len(known) != len(ids):
            raise ValueError('Semantic graph identities must be unique')
        if any(edge.source not in known or edge.target not in known for edge in self.edges):
            raise ValueError('Semantic graph has dangling endpoints')
        if any(block.parent_id and block.parent_id not in known for block in self.blocks):
            raise ValueError('Semantic graph has an unknown parent')
        return self
