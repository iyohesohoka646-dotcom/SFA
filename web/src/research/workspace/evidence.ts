import { useEffect, useState } from "react";
import { client } from "../client";
import type { SnapshotRef } from "../generated";
const cache = new Map<string, SnapshotRef>();
export function useSnapshot(id?: string) {
  const [value, setValue] = useState<SnapshotRef>(),
    [error, setError] = useState("");
  useEffect(() => {
    const abort = new AbortController();
    setError("");
    setValue(id ? cache.get(id) : undefined);
    if (id && !cache.has(id))
      void client
        .snapshot(id, abort.signal)
        .then((snapshot) => {
          if (snapshot.id !== id) throw new Error("数据版本不匹配");
          cache.set(id, snapshot);
          while (cache.size > 64) cache.delete(cache.keys().next().value!);
          if (!abort.signal.aborted) setValue(snapshot);
        })
        .catch((error) => {
          if (!abort.signal.aborted) setError(error.message);
        });
    return () => abort.abort();
  }, [id]);
  return { snapshot: value?.id === id ? value : undefined, error };
}
