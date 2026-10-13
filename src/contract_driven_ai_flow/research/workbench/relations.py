from .models import ProbeOutput, Relation


def relationship_output(research, snapshot_id):
    selected = research.store.snapshot(snapshot_id)
    parents, consumers, relations = [], [], []
    for parent_id in selected.parents:
        try:
            parent = research.store.snapshot(parent_id)
            if parent.run_id != selected.run_id:
                continue
            parents.append(
                {
                    "id": parent.id,
                    "name": parent.name,
                    "binding_id": parent.binding_id,
                    "version": parent.version,
                }
            )
            relations.append(
                Relation(
                    source=parent.id,
                    target=selected.id,
                    provenance=selected.provenance,
                    evidence=[selected.id],
                ).model_dump(mode="json")
            )
        except LookupError:
            pass
    # Bounded graph projection, retaining an explicit partial marker.
    candidates = research.store.snapshots(selected.run_id, latest=False, limit=1000)
    for value in candidates:
        if selected.id in value.parents:
            consumers.append(
                {
                    "id": value.id,
                    "name": value.name,
                    "binding_id": value.binding_id,
                    "version": value.version,
                }
            )
            relations.append(
                Relation(
                    source=selected.id,
                    target=value.id,
                    provenance=value.provenance,
                    evidence=[value.id],
                ).model_dump(mode="json")
            )
    return ProbeOutput(
        instance_id="relations:" + snapshot_id,
        definition_id="view.relationships",
        capability="view",
        execution="builtin",
        status="ready",
        run_id=selected.run_id,
        snapshot_id=selected.id,
        fidelity="metadata_only",
        provenance=selected.provenance,
        data={
            "selected": selected.id,
            "parents": parents,
            "consumers": consumers,
            "relations": relations,
            "partial": len(candidates) >= 1000,
            "meaning": "Direct evidence links; inferred links are not proof of execution",
        },
    )
