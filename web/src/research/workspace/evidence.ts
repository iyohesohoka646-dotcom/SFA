import { useResearchServices } from "./ResearchServices";
import { useEffect, useState } from "react";

import type { SnapshotRef } from "../generated";
const cache = new Map<string, SnapshotRef>();
export function useSnapshot(id?: string) {
  const { research: { client }, apiPrefix } = useResearchServices();
  const key = apiPrefix + ':' + id;
  const [value, setValue] = useState<SnapshotRef>(),
    [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setError("");
    setValue(id ? cache.get(key) : undefined);
    if (id && !cache.has(key))
      void client
        .snapshot(id, abort.signal)
        .then((snapshot) => {
          if (snapshot.id !== id) throw new Error("数据版本不匹配");
          if (abort.signal.aborted) return;
          cache.set(key, snapshot);
          while (cache.size > 64) cache.delete(cache.keys().next().value!);
          if (!abort.signal.aborted) setValue(snapshot);
        })
        .catch((error) => {
          if (!abort.signal.aborted) setError(error.message);
        });
    return () => abort.abort();
  }, [id, key, client]);
  return { snapshot: value?.id === id ? value : undefined, error };
}
