import { isGeneratedReviewMark, layoutReviewMarkers, reviewMarkerTone } from "@/lib/pdf-review/reviewMarks";
import type { LinkedIssue } from "@/lib/pdf-review/types";
const issue:LinkedIssue={id:'c1',title:'Bore fit',request:'Add H7',evidence:'Ø8 H7',remaining:'',verdict:'solved_correct',anchors:{}};
const target={issue,number:1,rect:{origin:{x:120,y:100},size:{width:30,height:20}}};
it('keeps comparison candidates neutral',()=>{
 expect(reviewMarkerTone({...issue,verdict:undefined})).toBe('neutral');
 expect(reviewMarkerTone(issue)).toBe('success');
 expect(reviewMarkerTone({...issue,verdict:'open'})).toBe('error');
 expect(reviewMarkerTone({...issue,verdict:'unclear'})).toBe('warning');
});
it('places a compact control outside the evidence',()=>{
 const marks=layoutReviewMarkers([target],600,400,60);
 expect(marks).toHaveLength(1);
 expect(marks[0]?.rect).toEqual({origin:{x:156,y:100},size:{width:60,height:24}});
});
it('combines close findings and preserves the most urgent status',()=>{
 const marks=layoutReviewMarkers([target,{...target,number:2,issue:{...issue,id:'c2',verdict:'open'}}],600,400,60);
 expect(marks).toHaveLength(1);
 expect(marks[0]?.targets).toHaveLength(2);
 expect(marks[0]?.tone).toBe('error');
});
it('omits controls when no clear space exists',()=>{
 expect(layoutReviewMarkers([{...target,rect:{origin:{x:0,y:0},size:{width:600,height:400}}}],600,400,60)).toEqual([]);
});
it('recognizes only the retired app-generated annotation IDs',()=>{
 expect(isGeneratedReviewMark('depth-review:v2:c1:hash:region')).toBe(true);
 expect(isGeneratedReviewMark('depth-review:c1:label')).toBe(true);
 expect(isGeneratedReviewMark('depth-review:c1:page-note')).toBe(true);
 expect(isGeneratedReviewMark('supervisor-note')).toBe(false);
 expect(isGeneratedReviewMark('manual-region')).toBe(false);
 expect(isGeneratedReviewMark('depth-review:user-note')).toBe(false);
});
