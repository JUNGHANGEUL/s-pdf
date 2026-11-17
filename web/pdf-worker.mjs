import {Engine} from './engine.mjs';
const engine=new Engine(progress=>postMessage({progress}));
let queue=Promise.resolve();
self.onmessage=event=>{
  queue=queue.then(()=>{
    const {request,method,args}=event.data;
    try{
      const result=engine.dispatch(method,args), transfer=[];
      if(result instanceof Uint8Array)transfer.push(result.buffer);
      else if(result?.bytes instanceof Uint8Array)transfer.push(result.bytes.buffer);
      postMessage({request,result},transfer);
    }catch(error){postMessage({request,error:{message:error.message||String(error),code:error.code||'ERROR'}});}
  });
};
postMessage({ready:true});
