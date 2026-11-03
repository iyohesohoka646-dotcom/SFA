import { useEffect, useMemo, useSyncExternalStore } from 'react';
export interface OperationState {status:'idle'|'running'|'completed'|'error'|'cancelled'; value?:unknown; error?:string;}
export class OperationController {
  state:OperationState={status:'idle'};
  private controller?:AbortController;
  private generation=0;
  private listeners=new Set<()=>void>();
  subscribe=(fn:()=>void)=>{this.listeners.add(fn);return()=>{this.listeners.delete(fn);};};
  getSnapshot=()=>this.state;
  private publish(state:OperationState){this.state=state;for(const fn of this.listeners)fn();}
  cancel=()=>{this.generation++;this.controller?.abort();this.controller=undefined;this.publish({status:'cancelled'});};
  run=async<T,>(fn:(signal:AbortSignal)=>Promise<T>):Promise<T|undefined>=>{
    this.controller?.abort();
    const generation=++this.generation,controller=new AbortController();this.controller=controller;
    this.publish({status:'running'});
    let abort=()=>{};
    const aborted=new Promise<never>((_,reject)=>{abort=()=>reject(new DOMException('Cancelled','AbortError'));controller.signal.addEventListener('abort',abort,{once:true});});
    try {
      const value=await Promise.race([Promise.resolve().then(()=>fn(controller.signal)),aborted]);
      if(generation!==this.generation) return;
      this.publish({status:'completed',value});return value;
    } catch(error) {
      if(generation!==this.generation || controller.signal.aborted) return;
      this.publish({status:'error',error:error instanceof Error?error.message:String(error)});
      return;
    } finally {controller.signal.removeEventListener('abort',abort);if(generation===this.generation)this.controller=undefined;}
  };
}
export function useOperation(key:string){
  const operation=useMemo(()=>new OperationController(),[key]);
  const state=useSyncExternalStore(operation.subscribe,operation.getSnapshot);
  useEffect(()=>()=>operation.cancel(),[operation]);
  return {...state,run:operation.run,cancel:operation.cancel};
}
