import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {createRequire} from 'node:module';
const require=createRequire(import.meta.url),{chromium}=require(process.env.PLAYWRIGHT_MODULE_ROOT?path.join(process.env.PLAYWRIGHT_MODULE_ROOT,'playwright'):'playwright');
const browser=await chromium.launch({headless:true,channel:'msedge'});
try{const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());await page.goto(process.env.SPDF_URL||'http://127.0.0.1:8765/');await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('준비 완료'));await page.locator('#demo-button').click();await page.waitForFunction(()=>spdf.summary().tabs.length&&!spdf.summary().busy);await page.locator('[data-mode=capture]').click();await page.locator('[data-capture-scope=page]').click();await page.locator('#capture-dpi').evaluate(el=>{el.value='1200';el.dispatchEvent(new Event('input',{bubbles:true}));});
const downloadEvent=page.waitForEvent('download',{timeout:120000});await page.locator('#capture-save').click();const download=await downloadEvent,folder=await fs.mkdtemp(path.join(os.tmpdir(),'spdf-quality-')),file=path.join(folder,'saved.png');await download.saveAs(file);await page.waitForFunction(()=>!spdf.summary().busy);const saved=await fs.readFile(file),hash=createHash('sha256').update(saved).digest('hex');assert.equal(saved.readUInt32BE(16),10000);assert.equal(saved.readUInt32BE(20),13334);
// Intercept only this test's clipboard writes; do not touch the user's clipboard.
await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{write:async items=>{const blob=await items[0].getType('image/png'),bytes=await blob.arrayBuffer(),view=new DataView(bytes),digest=await crypto.subtle.digest('SHA-256',bytes);window.testClipboard={hash:[...new Uint8Array(digest)].map(v=>v.toString(16).padStart(2,'0')).join(''),width:view.getUint32(16),height:view.getUint32(20)};}}}));
for(const trigger of ['button','keyboard','keyboard-range']){await page.evaluate(()=>window.testClipboard=null);if(trigger==='button')await page.locator('#capture-copy').click();else {if(trigger==='keyboard-range')await page.locator('#capture-dpi').focus();await page.keyboard.press('Control+c');}await page.waitForFunction(()=>window.testClipboard&&!spdf.summary().busy,{},{timeout:120000});const copied=await page.evaluate(()=>window.testClipboard);assert.equal(copied.hash,hash);assert.equal(copied.width,10000);assert.equal(copied.height,13334);console.log('PASS '+trigger+' creates exactly the same 133MP PNG bytes as image save');}
assert.deepEqual(errors,[]);assert.match(await page.locator('#toast').innerText(),/같은 해상도/);console.log('PASS large clipboard path, progress completion and lossless equality');
}finally{await browser.close();}
