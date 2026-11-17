export const CAPTURE_LIMITS={normal:60_000_000,png:240_000_000,side:32000};
export function capturePlan(area,{dpi=300,kind='png'}={}){
  if(area.length!==4||area.some(v=>!Number.isFinite(v))||area[2]<=area[0]||area[3]<=area[1])throw Error('캡처 영역을 확인해주세요.');
  const requested=dpi==='max'?Infinity:Number(dpi)/72;
  if(!(requested>0))throw Error('해상도를 확인해주세요.');
  const limit=kind==='png'||kind==='copy'?CAPTURE_LIMITS.png:CAPTURE_LIMITS.normal;
  const dimensions=scale=>[Math.ceil(area[2]*scale)-Math.floor(area[0]*scale),Math.ceil(area[3]*scale)-Math.floor(area[1]*scale)];
  let high=Math.min(Number.isFinite(requested)?requested:Infinity,Math.sqrt(limit/((area[2]-area[0])*(area[3]-area[1]))),CAPTURE_LIMITS.side/(area[2]-area[0]),CAPTURE_LIMITS.side/(area[3]-area[1])),low=0;
  const fits=s=>{const [w,h]=dimensions(s);return w*h<=limit&&w<=CAPTURE_LIMITS.side&&h<=CAPTURE_LIMITS.side;};
  if(!fits(high)){for(let i=0;i<48;i++){const mid=(low+high)/2;if(fits(mid))low=mid;else high=mid;}high=low;}
  const [width,height]=dimensions(high);
  return {scale:high,width,height,dpi:high*72,reduced:Number.isFinite(requested)&&high<requested*.99999,maximum:dpi==='max'};
}
