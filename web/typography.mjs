// Resolve missing glyphs before editing the PDF; never redact on failed layout.
export function cleanEditText(text){return text.normalize('NFC').replace(/[\r\n\t\u00a0\u202f]/g,' ').replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u00ad\u200b\u200e\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]/g,'').replaceAll('\u2011','\u2010');}
export function glyphPlan(text,candidates){const cleaned=cleanEditText(text),runs=[],missing=[];let fallback=false;
 for(const c of cleaned){let found;for(let i=0;i<candidates.length;i++){const candidate=candidates[i],gid=candidate.glyphs?.get(c)||candidate.face.encodeCharacter(c);if(gid){found={...candidate,gid,c};if(i)fallback=true;break;}}
  if(!found){missing.push(c);continue;}let run=runs.at(-1);if(!run||run.key!==found.key){run={...found,glyphs:[],text:'',advance:0};runs.push(run);}run.glyphs.push(found.gid);run.text+=c;run.advance+=found.face.advanceGlyph(found.gid);
 }
 if(missing.length){const list=[...new Set(missing)].slice(0,8).map(c=>`${c} (U+${c.codePointAt(0).toString(16).toUpperCase()})`).join(', ');throw Error(`지원하지 않는 문자가 있습니다: ${list}. 원본은 변경하지 않았습니다.`);}
 return {text:cleaned,runs,advance:runs.reduce((n,r)=>n+r.advance,0),fallback,normalized:cleaned!==text};
}
