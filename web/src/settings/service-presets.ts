import type {ProviderProfile} from './client';
export const newProfile=():ProviderProfile=>({id:'',protocol:'openai-compatible',base_url:'',models:[],default_model:'',timeout_seconds:60,credential_ref:null});

export type ServiceProtocol='openai-compatible'|'anthropic';
export interface ServicePreset{id:string;label:string;protocol:ServiceProtocol;base_url:string;}

// Optional, provider-neutral presets. Only protocol + base URL are set; no provider,
// credential, model list or default model is implied so saved IDs stay untouched.
export const servicePresets:ServicePreset[]=[
  {id:'openai-compatible',label:'通用 OpenAI-compatible',protocol:'openai-compatible',base_url:''},
  {id:'ollama',label:'本地 Ollama (v1)',protocol:'openai-compatible',base_url:'http://127.0.0.1:11434/v1'},
  {id:'anthropic',label:'Anthropic Messages',protocol:'anthropic',base_url:'https://api.anthropic.com/v1'},
];

export function applyPreset(profile:ProviderProfile,preset:ServicePreset):ProviderProfile{
  return {...profile,protocol:preset.protocol,base_url:preset.base_url};
}
