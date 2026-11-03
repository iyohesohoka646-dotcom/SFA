"""Contract example only: no folder parser or stream editor is registered."""
from pathlib import Path
from contract_driven_ai_flow.research.workbench.analysis import analyze_source
from contract_driven_ai_flow.research.workbench.semantics import MemberBlockProvider, StructuralBlockProvider


def stream_examples(source: Path):
    graph = analyze_source(source).graph
    members = [block.id for block in graph.blocks if block.kind == 'function']
    provider = MemberBlockProvider()
    return [provider.provide('stream:shared-a','Analysis A',graph,members),
            provider.provide('stream:shared-b','Analysis B',graph,members)]


def folder_contract(source: Path):
    graph = analyze_source(source).graph
    return StructuralBlockProvider('folder').provide('folder:lab', 'Lab', graph, graph.roots)
