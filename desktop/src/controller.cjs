// Independent startup attempts and teardown; inspired by DeepSeek Harness, no source copied.
class BackendController {
 constructor(create,publish){this.create=create;this.publish=publish;this.state='stopped';this.closed=false;}
 async start(){
  if(this.closed)throw Error('Desktop is closed');
  if(this.state==='ready')return this.handle;
  if(this.pending)return this.pending;
  const attempt={cancelled:false};this.attempt=attempt;this.state='starting';this.publish(this.state);
  this.pending=(async()=>{
   try{
    attempt.host=this.create();const handle=await attempt.host.start();
    if(!attempt.cancelled){this.handle=handle;this.state='ready';this.publish(this.state);}
    return handle;
   }catch(error){await this.cleanup(attempt);if(!attempt.cancelled){this.state='error';this.publish(this.state,error);}throw error;}
   finally{this.pending=undefined;}
  })();return this.pending;
 }
 cleanup(attempt){return attempt.cleanup??=(async()=>{await attempt.host?.stop();})();}
 async close(){this.closed=true;if(this.attempt){this.attempt.cancelled=true;await this.cleanup(this.attempt);}await this.pending?.catch(()=>{});this.state='stopped';}
}
module.exports={BackendController};
