import {headers,ApiError} from '../api';
import type {PublicProviderProfile,ProviderProfile,ConnectionResult} from './generated';
export type {PublicProviderProfile,ProviderProfile,ConnectionResult};
async function request<T>(path:string,options:{method?:string;body?:unknown;signal?:AbortSignal}={}):Promise<T>{
  const response=await fetch('/api/v1/settings'+path,{method:options.method||'GET',headers:headers(),body:options.body===undefined?undefined:JSON.stringify(options.body),signal:options.signal});
  if(!response.ok){const body=await response.json().catch(()=>({detail:'模型设置请求失败'}));throw new ApiError(typeof body.detail==='string'?body.detail:'模型配置无效，请检查字段。',response.status);}
  return response.json();
}
export const models={
  list:(signal?:AbortSignal)=>request<PublicProviderProfile[]>('/models',{signal}),
  vault:(signal?:AbortSignal)=>request<{available:boolean;plaintext_fallback:boolean}>('/credential-store',{signal}),
  save:(profile:ProviderProfile,secret?:string,signal?:AbortSignal)=>request<PublicProviderProfile>('/models/'+encodeURIComponent(profile.id),{method:'PUT',body:{profile,...(secret?{secret}:{})},signal}),
  test:(id:string,body:{inference:boolean;model?:string;operation_id:string},signal?:AbortSignal)=>request<ConnectionResult>('/models/'+encodeURIComponent(id)+'/test',{method:'POST',body,signal}),
  cancel:(id:string)=>request<{cancelled:boolean}>('/operations/'+encodeURIComponent(id)+'/cancel',{method:'POST'}),
};
export const newProfile=():ProviderProfile=>({id:'',protocol:'openai-compatible',base_url:'http://127.0.0.1:11434/v1',models:[],default_model:'',timeout_seconds:60,credential_ref:null});
