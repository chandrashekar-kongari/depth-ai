import type {
  AnnotationScope,
  AnnotationTransferItem,
} from "@embedpdf/plugin-annotation";
import type { PdfAnnotationObject } from "@embedpdf/models";
import type { WorkspaceSnapshot } from "@/lib/pdf-review/types";
import { isGeneratedReviewMark } from "@/lib/pdf-review/reviewMarks";

export function encodeAppearance(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const value of bytes) binary += String.fromCharCode(value);
  return btoa(binary);
}
function decodeAppearance(value: string): ArrayBuffer {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0))
    .buffer;
}
export async function reconcileAnnotations(
  api: Pick<AnnotationScope, "getPageAnnotations" | "getAnnotationById" | "deleteAnnotation" | "updateAnnotation" | "importAnnotations" | "commit">,
  records: WorkspaceSnapshot["state"]["annotations"][string],
  baselines: Map<string, PdfAnnotationObject>,
  managed: Set<string>,
  nativePages: number[] = []
) {
  records = Object.fromEntries(Object.entries(records ?? {}).filter(([id,record])=>!isGeneratedReviewMark(id) && !isGeneratedReviewMark(record.annotation.id)));
  const needed = new Set([
    ...nativePages,
    ...Object.values(records ?? {}).map((item) => item.annotation.pageIndex),
  ]);
  for (const pageIndex of needed) {
    const native = await api.getPageAnnotations({ pageIndex }).toPromise();
    for (const annotation of native) {
      if (isGeneratedReviewMark(annotation.id)) {
        api.deleteAnnotation(pageIndex,annotation.id);
        baselines.delete(annotation.id);
        managed.delete(annotation.id);
      } else if (!managed.has(annotation.id) && !baselines.has(annotation.id))
        baselines.set(annotation.id, annotation);
    }
  }
  for (const id of managed) {
    if (isGeneratedReviewMark(id)) {
      const current=api.getAnnotationById(id)?.object;
      if (current) api.deleteAnnotation(current.pageIndex,id);
      baselines.delete(id);
      managed.delete(id);
      continue;
    }
    if (records?.[id]) continue;
    const current = api.getAnnotationById(id)?.object;
    const original = baselines.get(id);
    if (current && original)
      api.updateAnnotation(current.pageIndex, id, original);
    else if (current) api.deleteAnnotation(current.pageIndex, id);
  }
  for (const record of Object.values(records ?? {})) {
    const annotation = { ...record.annotation };
    if (annotation.created) annotation.created = new Date(annotation.created);
    if (annotation.modified)
      annotation.modified = new Date(annotation.modified);
    const existing = api.getAnnotationById(annotation.id)?.object;
    if (record.deleted) {
      if (existing) api.deleteAnnotation(annotation.pageIndex, annotation.id);
    } else if (existing) {
      if (JSON.stringify(existing) !== JSON.stringify(annotation))
        api.updateAnnotation(annotation.pageIndex, annotation.id, annotation);
    } else {
      const item: AnnotationTransferItem = { annotation };
      if (record.appearance)
        item.ctx = { data: decodeAppearance(record.appearance) };
      api.importAnnotations([item]);
    }
    managed.add(annotation.id);
  }
  await api.commit().toPromise();
}
