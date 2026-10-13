import type {ComponentType} from 'react';
import type {SnapshotRef,ValueDescriptor} from './generated';
export interface RendererPlugin {protocolVersion:number;id:string;supports:(descriptor:ValueDescriptor)=>boolean;Component:ComponentType<{snapshot:SnapshotRef}>;}
export class RendererRegistry{
  private plugins:RendererPlugin[]=[];
  register(plugin:RendererPlugin){
    if(plugin.protocolVersion!==1)throw new Error('Renderer requires protocol v1');
    if(!plugin.id || this.plugins.some(p=>p.id===plugin.id))throw new Error('Renderer ID must be unique');
    this.plugins.push(plugin);
  }
  resolve(descriptor:ValueDescriptor){return this.plugins.find(plugin=>plugin.supports(descriptor));}
}
export const renderers=new RendererRegistry();
