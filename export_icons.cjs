const fs=require('node:fs'),path=require('node:path'),lucide=require('lucide');
const out=path.join(__dirname,'assets','icons');fs.mkdirSync(out,{recursive:true});
let count=0;
const names=new Set();
for(const file of ['window.py','style.py','dialogs.py']){
  const source=fs.readFileSync(path.join(__dirname,file),'utf8');
  for(const m of source.matchAll(/"([a-z]+(?:-[a-z0-9]+)*)"/g))names.add(m[1]);
}
for(const name of names){
  const key=name.split('-').map(p=>p[0].toUpperCase()+p.slice(1)).join('');
  const nodes=lucide.icons[key];if(!nodes)continue;
  const children=nodes.map(([tag,attrs])=>'<'+tag+' '+Object.entries(attrs).map(([key,value])=>key+'="'+String(value).replace(/&/g,'&amp;').replace(/"/g,'&quot;')+'"').join(' ')+'/>').join('');
  fs.writeFileSync(path.join(out,name+'.svg'),'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'+children+'</svg>');count++;
}
fs.copyFileSync(require.resolve('lucide/package.json').replace('package.json','LICENSE'),path.join(__dirname,'assets','Lucide-LICENSE.txt'));
console.log('Exported '+count+' bundled icons.');
