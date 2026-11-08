import type { Rect } from "@embedpdf/models";
import type { LinkedIssue } from "@/lib/pdf-review/types";

export type ReviewMarkerTone = "success" | "error" | "warning" | "neutral";

/** Reserved IDs from the retired automatic rectangle/status annotations. */
export function isGeneratedReviewMark(id: string): boolean {
  return id.startsWith("depth-review:") && /:(region|label|page-note)$/.test(id);
}

export function reviewMarkerTone(issue: LinkedIssue): ReviewMarkerTone {
  switch (issue.verdict) {
    case "solved_correct": return "success";
    case "open":
    case "solved_incorrect": return "error";
    case "unclear": return "warning";
    default: return "neutral";
  }
}

export interface ReviewMarkerTarget {
  issue: LinkedIssue;
  number: number;
  rect: Rect;
}
export interface PositionedReviewMarker {
  targets: ReviewMarkerTarget[];
  rect: Rect;
  tone: ReviewMarkerTone;
}

function intersects(a: Rect,b: Rect, gap=0): boolean {
  return a.origin.x < b.origin.x+b.size.width+gap && a.origin.x+a.size.width+gap>b.origin.x && a.origin.y<b.origin.y+b.size.height+gap && a.origin.y+a.size.height+gap>b.origin.y;
}

/** Place fixed-size controls outside evidence. Tight clusters share one control. */
export function layoutReviewMarkers(targets: ReviewMarkerTarget[], width: number, height: number, solvedWidth: number): PositionedReviewMarker[] {
  const groups: ReviewMarkerTarget[][]=[];
  for (const target of targets) {
    const group=groups.find((items)=>items.some((other)=>Math.hypot(target.rect.origin.x+target.rect.size.width/2-other.rect.origin.x-other.rect.size.width/2,target.rect.origin.y+target.rect.size.height/2-other.rect.origin.y-other.rect.size.height/2)<24));
    if (group) group.push(target); else groups.push([target]);
  }
  const placed: PositionedReviewMarker[]=[];
  const priority: Record<ReviewMarkerTone,number>={success:0,neutral:1,warning:2,error:3};
  for (const group of groups) {
    const first=group[0];
    if (!first) continue;
    const tone=group.reduce((highest,target)=>priority[reviewMarkerTone(target.issue)]>priority[highest]?reviewMarkerTone(target.issue):highest,reviewMarkerTone(first.issue));
    const w=group.length===1 && tone==='success'?solvedWidth:28;
    const h=24;
    const x0=Math.min(...group.map(t=>t.rect.origin.x));
    const y0=Math.min(...group.map(t=>t.rect.origin.y));
    const x1=Math.max(...group.map(t=>t.rect.origin.x+t.rect.size.width));
    const y1=Math.max(...group.map(t=>t.rect.origin.y+t.rect.size.height));
    const candidates=[[x1+6,y0],[x0-w-6,y0],[x0,y0-h-6],[x0,y1+6],[x1+6,y1-h],[x0-w-6,y1-h]];
    for (const [left=0,top=0] of candidates) {
      const rect:Rect={origin:{x:left,y:top},size:{width:w,height:h}};
      if (left<4 || top<4 || left+w>width-4 || top+h>height-4 || targets.some(t=>intersects(rect,t.rect,3)) || placed.some(p=>intersects(rect,p.rect,4))) continue;
      placed.push({targets:group,rect,tone});
      break;
    }
  }
  return placed;
}
