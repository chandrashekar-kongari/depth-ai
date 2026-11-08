import { Task, type PdfAnnotationObject, type PdfSquareAnnoObject, type PdfErrorReason } from '@embedpdf/models';
import { reconcileAnnotations } from '@/lib/pdf-review/embedpdf/adapter';
function resolved<T>(value:T):Task<T,PdfErrorReason>{const task=new Task<T,PdfErrorReason>();task.resolve(value);return task;}
function square(id:string):PdfSquareAnnoObject{return {id,type:5,pageIndex:0,rect:{origin:{x:20,y:30},size:{width:40,height:20}},color:'transparent',strokeColor:'#17834b',strokeWidth:1,strokeStyle:1,opacity:1,flags:[]};}
function annotationApi(objects:PdfAnnotationObject[]) {
 const current=new Map(objects.map(object=>[object.id,object]));
 const api:Parameters<typeof reconcileAnnotations>[0]={
  getPageAnnotations:()=>resolved([...current.values()]),
  getAnnotationById:(id)=>{const object=current.get(id);return object?{object,commitState:'synced'}:null;},
  deleteAnnotation:jest.fn((_page:number,id:string)=>{current.delete(id);}),
  updateAnnotation:jest.fn(),importAnnotations:jest.fn(),commit:()=>resolved(true),
 };
 return api;
}
it('cleans old generated boxes and labels without deleting supervisor or manual annotations',async()=>{
 const old=square('depth-review:v2:c1:hash:region');
 const label=square('depth-review:c1:label');
 const supervisor=square('supervisor-comment');
 const manual=square('manual-note');
 const api=annotationApi([old,label,supervisor,manual]);
 const baselines=new Map<string,PdfAnnotationObject>();
 const managed=new Set<string>();
 await reconcileAnnotations(api,{[old.id]:{annotation:old},[manual.id]:{annotation:{...manual,opacity:.5}}},baselines,managed,[0]);
 expect(api.deleteAnnotation).toHaveBeenCalledWith(0,old.id);
 expect(api.deleteAnnotation).toHaveBeenCalledWith(0,label.id);
 expect(api.deleteAnnotation).not.toHaveBeenCalledWith(0,supervisor.id);
 expect(api.deleteAnnotation).not.toHaveBeenCalledWith(0,manual.id);
 expect(api.updateAnnotation).toHaveBeenCalledWith(0,manual.id,expect.objectContaining({opacity:.5}));
 expect(api.importAnnotations).not.toHaveBeenCalled();
 expect(baselines.has(supervisor.id)).toBe(true);
 expect(baselines.has(old.id)).toBe(false);
});
it('never restores a retired automatic box from an older baseline',async()=>{
 const old=square('depth-review:v2:c1:hash:region');
 const api=annotationApi([old]);
 const baselines=new Map([[old.id,old]]);
 const managed=new Set([old.id]);
 await reconcileAnnotations(api,{},baselines,managed);
 expect(api.deleteAnnotation).toHaveBeenCalledWith(0,old.id);
 expect(api.updateAnnotation).not.toHaveBeenCalled();
 expect(baselines.size).toBe(0);
 expect(managed.size).toBe(0);
});
