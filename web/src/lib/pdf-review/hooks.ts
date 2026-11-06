"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  workspaceSchema,
  type DrawingEdit,
  type WorkspaceSnapshot,
} from "@/lib/pdf-review/types";

async function checkedSnapshot(response: Response): Promise<WorkspaceSnapshot> {
  if (!response.ok) throw new Error(String(response.status));
  return workspaceSchema.parse(await response.json());
}

export function useDrawingWorkspace(fileIds: string[]) {
  const source = fileIds.join("\n");
  const {
    data: opened,
    error: openError,
    mutate: reopen,
  } = useSWR(
    source ? ["drawing-workspace", source] : null,
    async ([, ids]: [string, string]) =>
      checkedSnapshot(
        await fetch("/api/engineering/workspaces", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ file_ids: ids.split("\n") }),
        })
      ),
    { revalidateOnFocus: false }
  );
  const { data, mutate } = useSWR(
    opened ? `/api/engineering/workspaces/${opened.id}` : null,
    async (url: string) => checkedSnapshot(await fetch(url)),
    { fallbackData: opened, refreshInterval: 3000, revalidateOnFocus: true }
  );
  const latest = useRef<WorkspaceSnapshot | undefined>(undefined);
  const queue = useRef<
    Array<{ id: string; edit: DrawingEdit; version?: number }>
  >([]);
  const running = useRef(false);
  const [pending, setPending] = useState(0);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (data && !running.current) latest.current = data;
  }, [data]);
  const drain = useCallback(async () => {
    if (running.current || !latest.current) return;
    running.current = true;
    setFailed(false);
    try {
      while (queue.current.length && latest.current) {
        const next = queue.current[0];
        if (!next) break;
        next.version ??= latest.current.version;
        const response = await fetch(
          `/api/engineering/workspaces/${latest.current.id}/commands`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...next.edit,
              command_id: next.id,
              expected_version: next.version,
            }),
          }
        );
        const snapshot = await checkedSnapshot(response);
        latest.current = snapshot;
        queue.current.shift();
        setPending(queue.current.length);
        await mutate(snapshot, { revalidate: false });
      }
    } catch {
      setFailed(true);
    } finally {
      running.current = false;
    }
  }, [mutate]);
  const submit = useCallback(
    (edit: DrawingEdit) => {
      queue.current.push({ id: crypto.randomUUID(), edit });
      setPending(queue.current.length);
      void drain();
    },
    [drain]
  );
  const reload = useCallback(async () => {
    if (running.current) return;
    queue.current = [];
    setPending(0);
    setFailed(false);
    const current = await mutate();
    if (current) latest.current = current;
  }, [mutate]);
  return {
    snapshot: data,
    openError,
    pending,
    failed,
    submit,
    retry: drain,
    reload,
    reopen,
  };
}
