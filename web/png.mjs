// Encode scanline bands without allocating the complete RGB image.
import {Zlib} from './vendor/fflate/browser.js';
const crcTable=Uint32Array.from({length:256},(_,n)=>{for(let k=0;k<8;k++)n=n&1?0xedb88320^(n>>>1):n>>>1;return n>>>0;});
function chunk(name,data){const out=new Uint8Array(data.length+12),view=new DataView(out.buffer);view.setUint32(0,data.length);for(let i=0;i<4;i++)out[4+i]=name.charCodeAt(i);out.set(data,8);let crc=0xffffffff;for(let i=4;i<out.length-4;i++)crc=crcTable[(crc^out[i])&255]^(crc>>>8);view.setUint32(out.length-4,(crc^0xffffffff)>>>0);return out;}
export function bandedPNG(width,height,dpi,readBand){
  const header=new Uint8Array(13),hv=new DataView(header.buffer);hv.setUint32(0,width);hv.setUint32(4,height);header[8]=8;header[9]=2;
  const density=new Uint8Array(9),dv=new DataView(density.buffer);dv.setUint32(0,Math.round(dpi/0.0254));dv.setUint32(4,Math.round(dpi/0.0254));density[8]=1;
  const parts=[new Uint8Array([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('pHYs',density)];let total=parts.reduce((n,b)=>n+b.length,0);
  const zlib=new Zlib({level:6},data=>{const part=chunk('IDAT',data);total+=part.length;if(total>300*1048576)throw Error('PNG 파일이 너무 큽니다. 영역을 나누어 저장해주세요.');parts.push(part);});
  const rows=Math.max(1,Math.min(512,Math.floor(4_000_000/(width*3)))),stride=width*3;
  for(let top=0;top<height;top+=rows){const count=Math.min(rows,height-top),pixels=readBand(top,count),filtered=new Uint8Array((stride+1)*count);for(let row=0;row<count;row++){const offset=row*(stride+1),source=row*stride;filtered[offset]=1;for(let x=0;x<stride;x++)filtered[offset+1+x]=(pixels[source+x]-(x>=3?pixels[source+x-3]:0))&255;}zlib.push(filtered,top+count===height);}
  const end=chunk('IEND',new Uint8Array());parts.push(end);total+=end.length;const result=new Uint8Array(total);let offset=0;for(const part of parts){result.set(part,offset);offset+=part.length;}return result;
}
