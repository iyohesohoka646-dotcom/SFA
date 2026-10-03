const {spawn}=require('node:child_process');
const {createInterface}=require('node:readline');
class BackendHost {
 constructor(python,project){this.python=python;this.project=project;}
 start(){return new Promise((resolve,reject)=>{
  this.child=spawn(this.python,['-u','-X','utf8','-m','contract_driven_ai_flow.application.desktop_host','--project',this.project],{windowsHide:true,stdio:['pipe','pipe','pipe'],env:{...process.env,PYTHONUTF8:'1',PYTHONNOUSERSITE:'1'}});
  this.child.on('error',()=>reject(Error('Python runtime unavailable. Choose an installed tool runtime or reinstall the desktop package.')));
  // A failed spawn emits close without exit. Teardown must not wait on an
  // event that will never arrive and delay the visible error by six seconds.
  this.exited=new Promise(resolve=>this.child.once('close',resolve));
  this.child.stderr.on('data',()=>{});
  const lines=createInterface({input:this.child.stdout});
  lines.on('line',line=>{try{const state=JSON.parse(line);if(state.state==='ready'){this.handle=state;resolve(state);}else if(state.state==='error')reject(Error(state.message));}catch{reject(Error('Backend returned an invalid startup message'));}});
  this.child.on('exit',()=>{if(!this.handle)reject(Error('Backend exited before readiness'));});
 });}
 async stop(){
  if(!this.child)return;
  this.child.stdin.end('stop\n');
  let timer;await Promise.race([this.exited,new Promise(resolve=>{timer=setTimeout(()=>{this.child.kill();resolve();},6000);})]);clearTimeout(timer);
 }
}
module.exports={BackendHost};
