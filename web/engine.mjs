// S.PDF Web — all PDF operations run locally in a worker. AGPL-3.0-or-later.
import mupdf, {emptyStore} from './vendor/mupdf/mupdf.js';
import {bandedPNG} from './png.mjs';
import {CAPTURE_LIMITS} from './capture.mjs';
import {glyphPlan} from './typography.mjs';

export const VERSION = '3.5.0';
const MAX_PIXELS = 60_000_000;
const drop = (...objects) => objects.forEach(object => object?.destroy?.());
const intersect = (a,b) => a[0]<b[2] && a[2]>b[0] && a[1]<b[3] && a[3]>b[1];
const numeric = value => Number(Number(value).toFixed(5));
const rgb = hex => [1,3,5].map(index=>parseInt(hex.slice(index,index+2),16)/255);

export function pageRange(expression, count) {
  if (!expression || /^(all|전체|\*)$/i.test(expression.trim())) return Array.from({length:count},(_,i)=>i);
  const pages = [];
  for (const piece of expression.replaceAll('–','-').replaceAll('~','-').split(',')) {
    const match = piece.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) throw Error('페이지를 확인해주세요. 예: 1,3-5,8');
    const a=+match[1], b=+(match[2]||match[1]);
    if (a<1 || b<a || b>count) throw Error(`페이지는 1~${count} 범위로 입력해주세요.`);
    for(let p=a-1;p<b;p++) if(!pages.includes(p)) pages.push(p);
  }
  return pages;
}

function dictionaryCopy(doc, original) {
  const copy = doc.newDictionary();
  if (!original.isNull()) original.forEach((value,key)=>copy.put(key,value));
  return copy;
}

function pageResource(doc,page,type,name,value) {
  const object=page.getObject(), inherited=object.getInheritable('Resources');
  const resources=dictionaryCopy(doc,inherited), original=resources.get(type);
  const collection=dictionaryCopy(doc,original);
  collection.put(name,value); resources.put(type,collection); object.put('Resources',resources);
  drop(collection,original,resources,inherited,object);
}

function appendContent(doc,page,content) {
  const object=page.getObject(), old=object.get('Contents'), contents=doc.newArray();
  if (old.isArray()) old.forEach(value=>contents.push(value));
  else if(!old.isNull()) contents.push(old);
  const stream=doc.addStream(content,{});
  contents.push(stream); object.put('Contents',contents);
  drop(stream,contents,old,object);
}

export class Engine {
  constructor(progress=()=>{}) { this.documents=new Map(); this.sequence=0; this.progress=progress; this.fonts=new Map(); }
  font(name='ko') { if(!this.fonts.has(name)) this.fonts.set(name,new mupdf.Font(name)); return this.fonts.get(name); }
  record(doc,name,baseDirty=false,password='') {
    doc.disableJS(); doc.enableJournal();
    const id='pdf-'+(++this.sequence);
    this.documents.set(id,{doc,name,saved:0,baseDirty,password,revision:0,sourceFonts:new Map(),fontPointers:new Map()});
    return this.meta(id);
  }
  get(id) { const item=this.documents.get(id); if(!item) throw Error('문서를 다시 열어주세요.'); return item; }
  meta(id) {
    const item=this.get(id), journal=item.doc.getJournal();
    return {id,name:item.name,count:item.doc.countPages(),dirty:item.baseDirty||journal.position!==item.saved,
      undo:item.doc.canUndo(),redo:item.doc.canRedo(),revision:item.revision,protected:!!item.password,
      permissions:{edit:item.doc.hasPermission('edit'),copy:item.doc.hasPermission('copy'),print:item.doc.hasPermission('print'),assemble:item.doc.hasPermission('assemble'),annotate:item.doc.hasPermission('annotate')}};
  }
  open({bytes,name,password='',recovered=false}) {
    let doc;
    try {
      doc=new mupdf.PDFDocument(bytes);
      if(doc.needsPassword() && !doc.authenticatePassword(password)) { const error=Error(password?'비밀번호가 맞지 않습니다.':'비밀번호가 필요한 PDF입니다.'); error.code='PASSWORD'; throw error; }
      return this.record(doc,name,recovered,password);
    } catch(error) { drop(doc); throw error; }
  }
  close({id}) { const item=this.get(id);for(const record of item.sourceFonts.values())drop(record.face);item.sourceFonts.clear();item.doc.destroy(); this.documents.delete(id); emptyStore(); return true; }
  operation(id,label,action,permission='edit') {
    const item=this.get(id);
    if(!item.doc.hasPermission(permission)) throw Error('문서에 설정된 편집 권한을 확인해주세요.');
    item.doc.beginOperation(label);
    try { action(item.doc); item.doc.endOperation(); item.revision++; return this.meta(id); }
    catch(error) { try{item.doc.abandonOperation();}catch{} throw error; }
  }
  history({id,action}) {
    const item=this.get(id);
    if(action==='undo' && item.doc.canUndo()) item.doc.undo();
    if(action==='redo' && item.doc.canRedo()) item.doc.redo();
    item.revision++; return this.meta(id);
  }
  page(id,index) {
    const doc=this.get(id).doc;
    if(!Number.isInteger(index)||index<0||index>=doc.countPages()) throw Error('페이지를 찾을 수 없습니다.');
    return doc.loadPage(index);
  }
  render({id,page:pageIndex=0,scale=1,clip=null,format='png',quality=92,excludeAnnotations=[],largePNG=false}) {
    const page=this.page(id,pageIndex), bounds=page.getBounds();
    const area=clip||bounds;
    const box=[Math.floor(area[0]*scale),Math.floor(area[1]*scale),Math.ceil(area[2]*scale),Math.ceil(area[3]*scale)],width=box[2]-box[0],height=box[3]-box[1];
    if(!Number.isFinite(scale)||scale<=0||width<=0||height<=0||width>CAPTURE_LIMITS.side||height>CAPTURE_LIMITS.side||width*height>(largePNG&&format==='png'?CAPTURE_LIMITS.png:MAX_PIXELS)) { drop(page); throw Error('이미지가 너무 큽니다. 해상도·확대 배율을 낮추거나 영역을 줄여주세요.'); }
    if(largePNG&&format==='png'&&width*height>MAX_PIXELS){try{const bytes=bandedPNG(width,height,scale*72,(top,count)=>{let pix,device;try{pix=new mupdf.Pixmap(mupdf.ColorSpace.DeviceRGB,[box[0],box[1]+top,box[2],box[1]+top+count],false);pix.clear(255);device=new mupdf.DrawDevice(mupdf.Matrix.scale(scale,scale),pix);page.run(device,mupdf.Matrix.identity);device.close();const pixels=pix.getPixels(),stride=pix.getStride(),out=new Uint8Array(width*3*count);for(let row=0;row<count;row++)out.set(pixels.subarray(row*stride,row*stride+width*3),row*width*3);this.progress({label:'초고화질 PNG 만들기',current:top+count,total:height});return out;}finally{drop(device,pix);}});return{bytes,width,height,bounds,format};}finally{drop(page);}}
    let pixmap,device,temporary=false,annotations=[];
    try {
      if(excludeAnnotations.length){this.get(id).doc.beginOperation('주석 드래그 미리보기');temporary=true;annotations=page.getAnnotations();for(const i of excludeAnnotations)if(annotations[i]){annotations[i].setFlags(annotations[i].getFlags()|2);annotations[i].update();}}
      if(clip) {
        const box=[Math.floor(area[0]*scale),Math.floor(area[1]*scale),Math.ceil(area[2]*scale),Math.ceil(area[3]*scale)];
        pixmap=new mupdf.Pixmap(mupdf.ColorSpace.DeviceRGB,box,false); pixmap.clear(255);
        device=new mupdf.DrawDevice(mupdf.Matrix.scale(scale,scale),pixmap);
        page.run(device,mupdf.Matrix.identity); device.close();
      } else pixmap=page.toPixmap(mupdf.Matrix.scale(scale,scale),mupdf.ColorSpace.DeviceRGB,false,true);
      pixmap.setResolution(Math.round(scale*72),Math.round(scale*72));
      return {bytes:(format==='jpg'?pixmap.asJPEG(quality,false):pixmap.asPNG()).slice(),width:pixmap.getWidth(),height:pixmap.getHeight(),bounds,format};
    } finally {drop(...annotations,device,pixmap,page);if(temporary)this.get(id).doc.abandonOperation();}
  }
  text({id,page:index=0}) {
    const page=this.page(id,index), text=page.toStructuredText('preserve-whitespace');
    const lines=[],item=this.get(id); let line;const colorHex=color=>{const values=color.length===1?[color[0],color[0],color[0]]:color.length===4?[0,1,2].map(i=>1-Math.min(1,color[i]+color[3])):color;return '#'+values.map(v=>Math.round(v*255).toString(16).padStart(2,'0')).join('');};
    try {
      text.walk({beginLine:(bbox,wmode,dir)=>{line={rect:bbox,dir,wmode,text:'',chars:[],size:12,origin:[bbox[0],bbox[3]]};},
        onChar:(c,origin,font,size,quad,color)=>{try{if(!line)return;let key=item.fontPointers.get(font.pointer);if(!key){key='source-'+(++this.sequence);const face=new mupdf.Font(font.pointer);item.sourceFonts.set(key,{key,face,name:face.getName(),bold:face.isBold(),italic:face.isItalic(),serif:face.isSerif(),mono:face.isMono(),pages:new Set()});item.fontPointers.set(font.pointer,key);}item.sourceFonts.get(key).pages.add(index);if(!line.text){line.origin=origin;line.size=size;line.color=colorHex(color);}line.text+=c;line.chars.push({c,quad,fontKey:key});line.fontCounts||={};line.fontCounts[key]=(line.fontCounts[key]||0)+1;}finally{drop(font);}},
        endLine:()=>{if(line?.text.trim()){line.fontKey=Object.keys(line.fontCounts).sort((a,b)=>line.fontCounts[b]-line.fontCounts[a])[0];line.fontName=item.sourceFonts.get(line.fontKey).name;delete line.fontCounts;lines.push(line);}line=null;}});
      return {lines,text:text.asText(),bounds:page.getBounds()};
    } finally { drop(text,page); }
  }
  copyText({id,page:index=0,rect}) {
    if(!this.get(id).doc.hasPermission('copy')) throw Error('텍스트 복사가 제한된 문서입니다.');
    return this.text({id,page:index}).lines.filter(line=>intersect(line.rect,rect)).map(line=>line.text).join('\n');
  }
  search({id,query}) {
    const doc=this.get(id).doc, matches=[];
    if(!query.trim()) return matches;
    for(let p=0;p<doc.countPages();p++) {
      const page=doc.loadPage(p);
      try { const quads=page.search(query); if(quads.length) matches.push({page:p,quads}); }
      finally { drop(page); }
      if(p%8===0) this.progress({label:'문서 검색',current:p+1,total:doc.countPages()});
    }
    return matches;
  }
  editPages({id,action,pages,order,delta=90}) {
    const item=this.get(id), count=item.doc.countPages();
    const selected=[...new Set(pages||[])];
    if(selected.some(p=>!Number.isInteger(p)||p<0||p>=count)) throw Error('선택한 페이지를 확인해주세요.');
    if(action==='delete'&&selected.length>=count) throw Error('문서에는 한 페이지 이상 남아 있어야 합니다.');
    if(action==='reorder' && (order.length!==count||new Set(order).size!==count||order.some(p=>p<0||p>=count))) throw Error('페이지 순서가 올바르지 않습니다.');
    return this.operation(id,{'delete':'페이지 삭제','rotate':'페이지 회전','reorder':'페이지 순서 변경'}[action],doc=>{
      if(action==='delete') selected.sort((a,b)=>b-a).forEach(p=>doc.deletePage(p));
      else if(action==='reorder') doc.rearrangePages(order);
      else if(action==='rotate') for(const p of selected){const object=doc.findPage(p),current=object.getInheritable('Rotate');object.put('Rotate',((current.asNumber()+delta)%360+360)%360);drop(current,object);}
      else throw Error('지원하지 않는 페이지 작업입니다.');
    },'assemble');
  }
  merge({ids,name='합친 문서.pdf',target=null,at=null}) {
    if(!ids.length) throw Error('합칠 문서를 선택해주세요.');
    const sources=ids.map(id=>this.get(id).doc);
    for(const source of sources) if(!source.hasPermission('assemble')) throw Error('페이지 병합이 제한된 문서가 있습니다.');
    if(target && ids.includes(target)) throw Error('같은 문서를 자기 자신에 덧붙일 수 없습니다.');
    const append=doc=>{let position=at===null?doc.countPages():Math.max(0,Math.min(at,doc.countPages()));for(const source of sources){const graft=doc.newGraftMap();try{for(let p=0;p<source.countPages();p++)graft.graftPage(position++,source,p);}finally{drop(graft);}}};
    if(target) return this.operation(target,'PDF 덧붙이기',append,'assemble');
    const doc=new mupdf.PDFDocument();
    try {append(doc);return this.record(doc,name,true);} catch(error){drop(doc);throw error;}
  }
  extract({id,pages}) {
    const source=this.get(id).doc, output=new mupdf.PDFDocument(), graft=output.newGraftMap();
    if(!source.hasPermission('assemble')) {drop(graft,output);throw Error('페이지 추출이 제한된 문서입니다.');}
    try {for(const p of pages){if(p<0||p>=source.countPages())throw Error('추출 페이지를 확인해주세요.');graft.graftPage(-1,source,p);}const bytes=output.saveToBuffer('compress=yes,garbage=4');try{return bytes.asUint8Array().slice();}finally{drop(bytes);}}
    finally{drop(graft,output);}
  }
  textPlan(id,text,font='auto',sourceFontKey=null){
    const item=this.get(id),original=item.sourceFonts.get(sourceFontKey),auto=font==='auto',candidates=[];
    if(auto&&original&&[...text].some(c=>!original.face.encodeCharacter(c))){
      item.glyphPages||=new Map();
      for(const index of original.pages||[]){if(item.glyphPages.get(index)===item.revision)continue;const page=this.page(id,index);let device;
        const collect=(text,...objects)=>{try{text.walk({showGlyph:(font,trm,gid,unicode)=>{const record=item.sourceFonts.get(item.fontPointers.get(font.pointer));if(record&&gid>0&&unicode>0){record.glyphs||=new Map();record.glyphs.set(String.fromCodePoint(unicode),gid);}}});}finally{drop(text,...objects.filter(o=>o?.destroy));}};
        try{device=new mupdf.Device({fillText:collect,strokeText:collect,ignoreText:collect,clipText:collect,clipStrokeText:collect});page.runPageContents(device,mupdf.Matrix.identity);device.close();item.glyphPages.set(index,item.revision);}finally{drop(device,page);}
      }
    }
    if(auto&&original){if(original.embeddable===undefined){const probe=new mupdf.PDFDocument();let ref;try{ref=probe.addFont(original.face);original.embeddable=true;}catch{original.embeddable=false;}finally{drop(ref,probe);}}if(original.embeddable)candidates.push({...original,original:true});}
    const suffix=original?.bold?(original?.italic?'BoldItalic':'Bold'):(original?.italic?'Italic':'');
    const latin=original?.mono?('Courier'+(suffix?'-'+(suffix==='Italic'?'Oblique':suffix==='BoldItalic'?'BoldOblique':suffix):'')):original?.serif?(suffix?'Times-'+suffix:'Times-Roman'):('Helvetica'+(suffix?'-'+(suffix==='Italic'?'Oblique':suffix==='BoldItalic'?'BoldOblique':suffix):''));
    const names=auto?(original?[latin,'ko','Helvetica','Symbol','ZapfDingbats']:['ko','Helvetica','Symbol','ZapfDingbats']):[font,'ko','Helvetica','Symbol','ZapfDingbats'];
    for(const name of [...new Set(names)]){const face=this.font(name);candidates.push({key:'builtin-'+name,face,name:face.getName(),bold:auto&&!!original?.bold&&!face.isBold(),italic:auto&&!!original?.italic&&!face.isItalic()});}
    const plan=glyphPlan(text,candidates);plan.source=auto?original?.name:null;plan.sourceMatched=auto&&!!original&&plan.runs.some(r=>r.original);plan.substituted=auto&&!!original&&plan.runs.some(r=>!r.original);return plan;
  }
  insertText(doc,page,{text,origin,size=12,color='#202c42',font='auto',invisible=false,width=null,fit=true,plan=null}) {
    if(!plan)plan=this.textPlan([...this.documents].find(([,item])=>item.doc===doc)?.[0],text,font);
    if(width&&plan.advance*size>width+.01){if(!fit)throw Error('글자가 선택 영역보다 깁니다. 크기를 줄여주세요.');size=width/plan.advance;if(size<4)throw Error('내용이 너무 깁니다. 영역을 넓히거나 글자 수를 줄여주세요.');}
    const matrix=mupdf.Matrix.invert(page.getTransform()).map(numeric).join(' '),ink=rgb(color).map(numeric).join(' ');let x=origin[0];
    for(const run of plan.runs){let ref=doc.addFont(run.face);const name='SPDF_Font_'+(++this.sequence);
      if(run.original){const mapping=new Map();const chars=[...run.text];run.glyphs.forEach((gid,i)=>mapping.set(gid,chars[i]));const rows=[...mapping].map(([gid,c])=>`<${gid.toString(16).padStart(4,'0')}> <${Array.from({length:c.length},(_,i)=>c.charCodeAt(i).toString(16).padStart(4,'0')).join('')}>`);let cmap='/CIDInit /ProcSet findresource begin 12 dict begin begincmap /CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def /CMapName /SPDFUnicode def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> endcodespacerange\n';for(let i=0;i<rows.length;i+=100)cmap+=`${Math.min(100,rows.length-i)} beginbfchar\n${rows.slice(i,i+100).join('\n')}\nendbfchar\n`;cmap+='endcmap CMapName currentdict /CMap defineresource pop end end';const dict=dictionaryCopy(doc,ref),unicode=doc.addStream(cmap,{}),copy=doc.addObject(dict);copy.put('ToUnicode',unicode);drop(dict,unicode,ref);ref=copy;}
      pageResource(doc,page,'Font',name,ref);drop(ref);const hex=run.glyphs.map(gid=>gid.toString(16).padStart(4,'0')).join('');appendContent(doc,page,`q ${matrix} cm BT /${name} ${numeric(size)} Tf ${invisible?'3':run.bold&&!run.original?'2':'0'} Tr ${numeric(size*.018)} w ${ink} rg ${ink} RG 1 0 ${run.italic&&!run.original?'.2':'0'} -1 ${numeric(x)} ${numeric(origin[1])} Tm <${hex}> Tj ET Q\n`);x+=run.advance*size;}
  }
  editText({id,page:index=0,rect,text,size=12,color=null,font='auto',sourceFontKey=null,replace=false,origin=null,fit=true,clearImage=false}) {
    if(!text.trim())throw Error('새로 넣을 글자를 입력해주세요.');
    let sourceLine;if(replace&&!sourceFontKey){sourceLine=this.text({id,page:index}).lines.filter(l=>intersect(l.rect,rect)).sort((a,b)=>Math.hypot(a.rect[0]-rect[0],a.rect[1]-rect[1])-Math.hypot(b.rect[0]-rect[0],b.rect[1]-rect[1]))[0];sourceFontKey=sourceLine?.fontKey;}
    const plan=this.textPlan(id,text,font,sourceFontKey);if(!plan.text.trim())throw Error('새로 넣을 글자를 입력해주세요.');
    if(plan.advance*size>rect[2]-rect[0]+.01&&(!fit||(rect[2]-rect[0])/plan.advance<4))throw Error('내용이 너무 깁니다. 영역을 넓히거나 글자 크기를 줄여주세요.');
    const meta=this.operation(id,replace?'기존 글자 수정':'글자 추가',doc=>{const page=doc.loadPage(index);try{
      if(replace){const redact=page.createAnnotation('Redact');redact.setRect(rect);redact.update();drop(redact);page.applyRedactions(false,clearImage?2:0,0,0);}
      this.insertText(doc,page,{text:plan.text,origin:origin||sourceLine?.origin||[rect[0],rect[1]+size],size,color:color||sourceLine?.color||'#202c42',width:rect[2]-rect[0],fit,plan});
    }finally{drop(page);}});
    return {...meta,textEdit:{sourceFont:plan.source,sourceMatched:plan.sourceMatched,substituted:plan.substituted,fallback:plan.fallback,normalized:plan.normalized,usedFonts:[...new Set(plan.runs.map(r=>r.name))]}};
  }
  annotate({id,page:index=0,type='Highlight',rect,color='#f0b92f',text='',arrow=true,line=null}) {
    return this.operation(id,'주석 추가',doc=>{
      const page=doc.loadPage(index), annotation=page.createAnnotation(type);
      try {
        annotation.setColor(rgb(color));annotation.setAuthor('S.PDF');
        if(type==='Line'){annotation.setLine(...(line||[[rect[0],rect[1]],[rect[2],rect[3]]]));annotation.setLineEndingStyles('None',arrow?'ClosedArrow':'None');annotation.setBorderWidth(2);}
        else if(type==='Highlight'){annotation.setQuadPoints([[rect[0],rect[1],rect[2],rect[1],rect[0],rect[3],rect[2],rect[3]]]);annotation.setOpacity(.4);}
        else {annotation.setRect(rect);if(type==='Square')annotation.setBorderWidth(1.5);}
        if(text)annotation.setContents(text);
        annotation.update();
      } finally{drop(annotation,page);}
    },'annotate');
  }
  updateAnnotations({id,page:index=0,changes=[],remove=[]}) {
    return this.operation(id,'주석 편집',doc=>{const page=doc.loadPage(index),list=page.getAnnotations();try{
      for(const change of changes){const a=list[change.index];if(!a)continue;
        if(change.color)a.setColor(rgb(change.color));if(change.text!==undefined)a.setContents(change.text);
        if(change.line)a.setLine(...change.line);
        else if(change.rect){const old=a.getBounds(),r=change.rect,map=p=>[r[0]+(p[0]-old[0])*(r[2]-r[0])/(old[2]-old[0]||1),r[1]+(p[1]-old[1])*(r[3]-r[1])/(old[3]-old[1]||1)];
          if(a.getType()==='Line')a.setLine(...a.getLine().map(map));else if(a.getType()==='Highlight')a.setQuadPoints(a.getQuadPoints().map(q=>{let n=[];for(let i=0;i<8;i+=2)n.push(...map([q[i],q[i+1]]));return n;}));else a.setRect(r);
        }a.update();}
      for(const index of [...remove].sort((a,b)=>b-a))if(list[index])page.deleteAnnotation(list[index]);
    }finally{drop(...list,page);}},'annotate');
  }
  annotations({id,page:index=0}) {
    const page=this.page(id,index);
    try{return page.getAnnotations().map((a,i)=>({index:i,type:a.getType(),text:a.getContents(),rect:a.getBounds(),width:a.getBorderWidth(),color:'#'+a.getColor().slice(0,3).map(v=>Math.round(v*255).toString(16).padStart(2,'0')).join(''),line:a.getType()==='Line'?a.getLine():null,endings:a.getType()==='Line'?a.getLineEndingStyles():null}));}
    finally{drop(page);}
  }
  deleteAnnotation({id,page:index=0,index:annotationIndex}) {
    return this.operation(id,'주석 삭제',doc=>{const page=doc.loadPage(index);try{const annotations=page.getAnnotations();if(!annotations[annotationIndex])throw Error('주석을 찾을 수 없습니다.');page.deleteAnnotation(annotations[annotationIndex]);}finally{drop(page);}},'annotate');
  }
  bookmarks({id}) {
    const doc=this.get(id).doc,result=[];
    function visit(items,parent=[]){(items||[]).forEach((item,index)=>{const path=[...parent,index];let page=0;try{page=doc.resolveLink(item.uri);}catch{}result.push({title:item.title||'북마크',page,path,level:parent.length});visit(item.down,path);});}
    visit(doc.loadOutline());return result;
  }
  bookmark({id,page=0,title,path=null,remove=false}) {
    return this.operation(id,remove?'북마크 삭제':'북마크 추가',doc=>{
      const iterator=doc.outlineIterator();
      try {
        if(remove){for(let depth=0;depth<path.length;depth++){if(depth)iterator.down();for(let i=0;i<path[depth];i++)iterator.next();}iterator.delete();}
        else{while(iterator.item()!==null&&iterator.next()===0){}iterator.insert({title:title||`${page+1}페이지`,uri:`#page=${page+1}`,open:false});}
      } finally{drop(iterator);}
    });
  }
  addOverlay({id,page:index=0,bytes}) {
    const overlay=new mupdf.PDFDocument(bytes);
    try{return this.operation(id,'문자 인식 · OCR',doc=>{
      const source=overlay.loadPage(0), target=doc.loadPage(index), object=source.getObject();
      const bounds=source.getBounds(), targetBounds=target.getBounds(), original=object.get('Contents');
      const buffers=[];
      try {
        const collect=stream=>{const buffer=stream.readStream();try{buffers.push(buffer.asUint8Array().slice());}finally{drop(buffer);}};
        if(original.isArray())original.forEach(collect);else collect(original);
        const all=new Uint8Array(buffers.reduce((n,b)=>n+b.length+1,0));let offset=0;for(const buffer of buffers){all.set(buffer,offset);offset+=buffer.length;all[offset++]=10;}
        const resources=object.getInheritable('Resources'), transferred=doc.graftObject(resources), box=object.getInheritable('MediaBox');
        const form=doc.addStream(all,{Type:'XObject',Subtype:'Form',BBox:box.asJS(),Resources:transferred});
        const name='SPDF_OCR_'+(++this.sequence);pageResource(doc,target,'XObject',name,form);
        let matrix=mupdf.Matrix.concat(source.getTransform(),mupdf.Matrix.scale((targetBounds[2]-targetBounds[0])/(bounds[2]-bounds[0]),(targetBounds[3]-targetBounds[1])/(bounds[3]-bounds[1])));
        matrix=mupdf.Matrix.concat(matrix,mupdf.Matrix.translate(targetBounds[0],targetBounds[1]));
        matrix=mupdf.Matrix.concat(matrix,mupdf.Matrix.invert(target.getTransform()));
        appendContent(doc,target,`q ${matrix.map(numeric).join(' ')} cm /${name} Do Q\n`);
        drop(resources,transferred,box,form);
      }finally{drop(original,object,source,target);}
    });}finally{drop(overlay);}
  }
  compress({id,maxDimension=2400,quality=80}) {
    let changed=0;
    const meta=this.operation(id,'PDF 용량 줄이기',doc=>{
      const count=doc.countObjects();
      for(let i=1;i<count;i++) {
        let ref,image,pixmap,resized,rgbPixmap,newImage,newRef,raw;
        try {
          ref=doc.newIndirect(i);
          if(!ref.isStream()||ref.get('Subtype').asName()!=='Image'||!ref.get('SMask').isNull()||!ref.get('Mask').isNull()||ref.get('ImageMask').asBoolean())continue;
          image=doc.loadImage(ref);if(image.getWidth()<256&&image.getHeight()<256)continue;
          pixmap=image.toPixmap();
          if(pixmap.getNumberOfComponents()!==3){rgbPixmap=pixmap.convertToColorSpace(mupdf.ColorSpace.DeviceRGB,false);}
          let source=rgbPixmap||pixmap;
          const ratio=Math.min(1,maxDimension/Math.max(source.getWidth(),source.getHeight()));
          if(ratio<1){const w=source.getWidth(),h=source.getHeight();resized=source.warp([[0,0],[w,0],[0,h],[w,h]],Math.max(1,Math.round(w*ratio)),Math.max(1,Math.round(h*ratio)));source=resized;}
          const jpeg=source.asJPEG(quality,false);raw=ref.readRawStream();
          if(ratio===1&&jpeg.length>=raw.getLength())continue;
          newImage=new mupdf.Image(jpeg);newRef=doc.addImage(newImage);
          const dictionary=newRef.resolve(), data=newRef.readRawStream();
          try{ref.writeObject(dictionary);ref.writeRawStream(data);}finally{drop(dictionary,data);}
          changed++;
        } finally{drop(raw,newRef,newImage,resized,rgbPixmap,pixmap,image,ref);}
        if(i%15===0)this.progress({label:'이미지 용량 줄이기',current:i,total:count});
      }
    });
    return {meta,changed};
  }
  save({id,mark=true,password=null}) {
    const item=this.get(id);
    const options={compress:true,'compress-images':true,'compress-fonts':true,garbage:4,objstms:true};
    if(password!==null){options.encrypt=password?'aes-256':'none';if(password){options['user-password']=password;options['owner-password']=password;}}
    else options.encrypt='keep';
    // Garbage collection renumbers PDF objects. Write a separate document so
    // journal entries in the active document keep their original object IDs.
    const intermediate=item.doc.saveToBuffer('compress=yes,encrypt=keep');
    let copy,buffer;
    try{
      // The constructor can grow Wasm memory for large PDFs. A view into that
      // same memory would detach during the copy, so hand it JS-owned bytes.
      copy=new mupdf.PDFDocument(intermediate.asUint8Array().slice());
      if(copy.needsPassword()&&!copy.authenticatePassword(item.password))throw Error('저장할 문서의 비밀번호를 다시 확인해주세요.');
      buffer=copy.saveToBuffer(options);
      const bytes=buffer.asUint8Array().slice();if(mark){item.saved=item.doc.getJournal().position;item.baseDirty=false;}return {bytes,meta:this.meta(id)};
    }finally{drop(buffer,copy,intermediate);}
  }
  demo() {
    const doc=new mupdf.PDFDocument(), font=this.font(), ref=doc.addFont(font);
    const pages=[['S.PDF','문서 작업을 한곳에서.','여러 문서를 열고, 선명하게 캡처하고, 필요한 내용을 편집하세요.'],['고화질 캡처','선택한 영역을 더 선명하게.','캡처 탭에서 영역을 드래그하고 해상도를 선택하세요.'],['페이지와 글자 편집','PDF를 필요한 모습으로.','페이지 구성에서 순서를 바꾸거나 글자 편집에서 문장을 수정하세요.']];
    const encode=text=>[...text].map(c=>font.encodeCharacter(c).toString(16).padStart(4,'0')).join('');
    for(const [title,heading,body] of pages){const contents=`q .94 .96 1 rg 0 650 600 150 re f Q\nBT /F 18 Tf .21 .40 .93 rg 1 0 0 1 48 740 Tm <${encode(title)}> Tj /F 30 Tf .12 .17 .26 rg 1 0 0 1 48 680 Tm <${encode(heading)}> Tj /F 12 Tf 1 0 0 1 48 610 Tm <${encode(body)}> Tj ET\nq .21 .40 .93 RG 2 w 48 555 504 2 re S Q\nBT /F 16 Tf .12 .17 .26 rg 1 0 0 1 48 490 Tm <${encode('열기 · 보기 · 캡처 · 편집 · 저장')}> Tj /F 12 Tf .42 .47 .55 rg 1 0 0 1 48 450 Tm <${encode('PDF 파일은 이 브라우저에서만 처리합니다.')}> Tj 1 0 0 1 48 420 Tm <${encode('새 문서로 저장하면 원본 파일을 그대로 보관할 수 있습니다.')}> Tj ET`;
      const object=doc.addPage([0,0,600,800],0,{Font:{F:ref}},contents);doc.insertPage(-1,object);drop(object);}
    drop(ref);return this.record(doc,'S.PDF 사용 가이드.pdf',true);
  }
  dispatch(method,args={}) {
    const allowed=['open','close','meta','render','text','copyText','search','editPages','merge','extract','editText','annotate','annotations','updateAnnotations','deleteAnnotation','bookmarks','bookmark','addOverlay','compress','save','history','demo'];
    if(!allowed.includes(method))throw Error('지원하지 않는 요청입니다.');
    return this[method](args);
  }
}
