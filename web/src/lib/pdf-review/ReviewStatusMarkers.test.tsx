import { render, screen, setupUser } from "@tests/setup/test-utils";
import { ReviewStatusMarkers } from "@/lib/pdf-review/ReviewStatusMarkers";
import type { LinkedIssue } from "@/lib/pdf-review/types";
jest.mock('@embedpdf/plugin-scroll/react',()=>({useScroll:()=>({provides:{getRectPositionForPage:(_page:number,rect:{origin:{x:number;y:number};size:{width:number;height:number}})=>rect}})}));
jest.mock('@embedpdf/core/react',()=>({useDocumentState:()=>({document:{pages:[{size:{width:600,height:400}}]}})}));
const solved:LinkedIssue={id:'c1',title:'Width',request:'Correct width',evidence:'Correct',remaining:'',verdict:'solved_correct',anchors:{revised:{page:1,box:{x:.3,y:.3,width:.05,height:.05},pageLevel:false,quality:'located_text'}}};
it('shows solved text without adding an annotation or a region box',async()=>{
 const user=setupUser();const select=jest.fn();
 render(<ReviewStatusMarkers documentId="revised" pageIndex={0} issues={[solved]} original={false} onSelect={select}/>);
 expect(screen.getByText('Solved')).toBeInTheDocument();
 expect(screen.getByTestId('pdf-status-marker')).toHaveAttribute('data-tone','success');
 await user.click(screen.getByRole('button'));
 expect(select).toHaveBeenCalledWith('c1',1);
});
it('does not mark a solved request on the original',()=>{
 render(<ReviewStatusMarkers documentId="revised" pageIndex={0} issues={[solved]} original onSelect={jest.fn()}/>);
 expect(screen.queryByTestId('pdf-status-marker')).not.toBeInTheDocument();
});
it('shows a comparison candidate only when selected, with a neutral status',()=>{
 const comparison={...solved,id:'dc1',verdict:undefined};
 const {rerender}=render(<ReviewStatusMarkers documentId="revised" pageIndex={0} issues={[comparison]} original={false} onSelect={jest.fn()}/>);
 expect(screen.queryByTestId('pdf-status-marker')).not.toBeInTheDocument();
 rerender(<ReviewStatusMarkers documentId="revised" pageIndex={0} issues={[comparison]} original={false} selectedIssueId="dc1" onSelect={jest.fn()}/>);
 expect(screen.getByTestId('pdf-status-marker')).toHaveAttribute('data-tone','neutral');
 expect(screen.getByRole('button')).toHaveAccessibleName(expect.stringContaining('Comparison region'));
});
it('does not invent a location and cycles overlapping findings',async()=>{
 const user=setupUser();const select=jest.fn();
 const open={...solved,id:'c2',verdict:'open' as const};
 const unknown={...solved,id:'c3',anchors:{}};
 render(<ReviewStatusMarkers documentId="revised" pageIndex={0} issues={[solved,open,unknown]} selectedIssueId="c1" original={false} onSelect={select}/>);
 expect(screen.getAllByTestId('pdf-status-marker')).toHaveLength(1);
 expect(screen.getByTestId('pdf-status-marker')).toHaveAttribute('data-tone','error');
 await user.click(screen.getByRole('button'));
 expect(select).toHaveBeenCalledWith('c2',1);
});
