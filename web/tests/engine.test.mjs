import test from 'node:test';
import assert from 'node:assert/strict';
import mupdf from '../vendor/mupdf/mupdf.js';
import {Engine,pageRange} from '../engine.mjs';

function fixture(){const engine=new Engine();const meta=engine.demo();return {engine,id:meta.id};}
function finish(engine){for(const id of [...engine.documents.keys()])engine.close({id});}

test('page ranges validate and preserve order',()=>{assert.deepEqual(pageRange('3,1-2,3',5),[2,0,1]);assert.throws(()=>pageRange('1,8',5));});
test('multiple documents retain independent engine state and Korean text',()=>{
  const {engine,id}=fixture();const second=engine.demo();assert.equal(engine.meta(id).count,3);assert.notEqual(second.id,id);
  assert.match(engine.text({id}).text,/문서 작업을 한곳에서/);engine.editPages({id,action:'delete',pages:[1]});assert.equal(engine.meta(second.id).count,3);finish(engine);
});
test('delete, rotate, reorder, undo and redo preserve content',()=>{
  const {engine,id}=fixture();engine.editPages({id,action:'reorder',order:[2,0,1]});assert.match(engine.text({id}).text,/페이지와 글자 편집/);
  engine.editPages({id,action:'delete',pages:[1]});assert.equal(engine.meta(id).count,2);engine.history({id,action:'undo'});assert.equal(engine.meta(id).count,3);
  engine.editPages({id,action:'rotate',pages:[0]});const image=engine.render({id,scale:.5});assert.deepEqual([image.width,image.height],[400,300]);
  engine.history({id,action:'undo'});engine.history({id,action:'redo'});assert.equal(engine.render({id,scale:.2}).width,160);finish(engine);
});
test('full and clipped captures use actual document resolution',()=>{
  const {engine,id}=fixture();const full=engine.render({id,scale:2});assert.deepEqual([full.width,full.height],[1200,1600]);
  const crop=engine.render({id,clip:[40,50,240,150],scale:300/72});assert.deepEqual([crop.width,crop.height],[835,417]);
  assert.throws(()=>engine.render({id,scale:100}));finish(engine);
});
test('real Korean text replacement, undo after saving, and safe rejection',()=>{
  const {engine,id}=fixture();const line=engine.text({id}).lines.find(l=>l.text.includes('문서 작업을'));
  engine.editText({id,rect:line.rect,origin:line.origin,text:'새로운 PDF 문서',size:24,replace:true});
  assert.match(engine.text({id}).text,/새로운 PDF 문서/);assert.doesNotMatch(engine.text({id}).text,/문서 작업을 한곳에서/);
  const saved=engine.save({id});const reopened=engine.open({bytes:saved.bytes,name:'수정.pdf'});assert.match(engine.text({id:reopened.id}).text,/새로운 PDF 문서/);
  engine.history({id,action:'undo'});assert.match(engine.text({id}).text,/문서 작업을 한곳에서/);
  assert.throws(()=>engine.editText({id,rect:line.rect,origin:line.origin,text:'너무 긴 문장'.repeat(100),size:24,replace:true,fit:false}));
  assert.match(engine.text({id}).text,/문서 작업을 한곳에서/);finish(engine);
});
test('text added to a rotated page is searchable in the selected area',()=>{
  const {engine,id}=fixture();engine.editPages({id,action:'rotate',pages:[0]});
  engine.editText({id,rect:[40,40,300,100],text:'회전 페이지 테스트',size:18});const matches=engine.search({id,query:'회전 페이지 테스트'});
  assert.equal(matches.length,1);assert.ok(matches[0].quads[0][0][0]>=35&&matches[0].quads[0][0][0]<100);finish(engine);
});
test('merge includes unsaved edits and extraction writes only selected pages',()=>{
  const {engine,id}=fixture();engine.editPages({id,action:'delete',pages:[1]});const other=engine.demo();const merged=engine.merge({ids:[id,other.id]});assert.equal(merged.count,5);
  const bytes=engine.extract({id:merged.id,pages:[4,0]});const result=engine.open({bytes,name:'추출.pdf'});assert.equal(result.count,2);assert.match(engine.text({id:result.id}).text,/페이지와 글자 편집/);finish(engine);
});
test('annotations and PDF bookmarks survive save and reopen',()=>{
  const {engine,id}=fixture();engine.annotate({id,rect:[40,300,140,340],type:'Square',text:'확인 메모'});assert.equal(engine.annotations({id}).length,1);
  engine.bookmark({id,page:1,title:'캡처 안내'});engine.bookmark({id,page:2,title:'편집 안내'});assert.equal(engine.bookmarks({id}).length,2);
  const saved=engine.save({id});const result=engine.open({bytes:saved.bytes,name:'주석.pdf'});assert.equal(engine.annotations({id:result.id})[0].text,'확인 메모');assert.equal(engine.bookmarks({id:result.id})[1].page,2);
  engine.deleteAnnotation({id,index:0});assert.equal(engine.annotations({id}).length,0);engine.history({id,action:'undo'});assert.equal(engine.annotations({id}).length,1);finish(engine);
});
test('password output is protected and wrong passwords are rejected',()=>{
  const {engine,id}=fixture();const saved=engine.save({id,password:'spdf-1234'});assert.throws(()=>engine.open({bytes:saved.bytes,name:'잠금.pdf'}),e=>e.code==='PASSWORD');
  assert.throws(()=>engine.open({bytes:saved.bytes,name:'잠금.pdf',password:'wrong'}));const reopened=engine.open({bytes:saved.bytes,name:'잠금.pdf',password:'spdf-1234'});assert.equal(reopened.count,3);finish(engine);
});
test('OCR text-only overlays preserve page pixels and add searchable text',()=>{
  const {engine,id}=fixture();const before=engine.render({id,scale:.5}).bytes;
  const overlay=new mupdf.PDFDocument();const font=new mupdf.Font('Helvetica'),ref=overlay.addFont(font);
  const glyphs=[...'OCR TEST'].map(c=>font.encodeCharacter(c).toString(16).padStart(4,'0')).join('');
  const page=overlay.addPage([0,0,600,800],0,{Font:{F:ref}},`BT 3 Tr /F 20 Tf 1 0 0 1 70 400 Tm <${glyphs}> Tj ET`);overlay.insertPage(-1,page);
  const buffer=overlay.saveToBuffer('');engine.addOverlay({id,bytes:buffer.asUint8Array().slice()});
  assert.equal(engine.search({id,query:'OCR TEST'}).length,1);assert.deepEqual(engine.render({id,scale:.5}).bytes,before);
  engine.history({id,action:'undo'});assert.equal(engine.search({id,query:'OCR TEST'}).length,0);
  page.destroy();ref.destroy();font.destroy();buffer.destroy();overlay.destroy();finish(engine);
});
test('image compression reduces image dimensions and preserves text',()=>{
  const engine=new Engine(),doc=new mupdf.PDFDocument(),pixmap=new mupdf.Pixmap(mupdf.ColorSpace.DeviceRGB,[0,0,1200,800],false);pixmap.clear(128);
  const image=new mupdf.Image(pixmap),imageRef=doc.addImage(image),font=new mupdf.Font('Helvetica'),fontRef=doc.addFont(font);
  const glyphs=[...'SEARCHABLE'].map(c=>font.encodeCharacter(c).toString(16).padStart(4,'0')).join('');
  const page=doc.addPage([0,0,600,800],0,{XObject:{Im:imageRef},Font:{F:fontRef}},`q 600 0 0 400 0 0 cm /Im Do Q BT /F 20 Tf 1 0 0 1 40 600 Tm <${glyphs}> Tj ET`);doc.insertPage(-1,page);
  const meta=engine.record(doc,'압축.pdf');const result=engine.compress({id:meta.id,maxDimension:600,quality:75});assert.equal(result.changed,1);
  assert.equal(engine.search({id:meta.id,query:'SEARCHABLE'}).length,1);const saved=engine.save({id:meta.id});const reopened=engine.open({bytes:saved.bytes,name:'압축 결과.pdf'});assert.equal(reopened.count,1);assert.ok(engine.render({id:reopened.id,scale:.5}).bytes.length>0);
  page.destroy();fontRef.destroy();font.destroy();imageRef.destroy();image.destroy();pixmap.destroy();finish(engine);
});
