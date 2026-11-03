import type {SnapshotRef} from './generated';
import type {RendererRegistry} from './renderer-registry';

/** Example plugin: consumes portable evidence, never Python objects. */
export function PointCloudView({snapshot}:{snapshot:SnapshotRef}){
  const points=((snapshot.sample.values as unknown[][])||[]).slice(0,1024).filter((row):row is number[]=>row.length>=2&&typeof row[0]==='number'&&typeof row[1]==='number'&&Number.isFinite(row[0])&&Number.isFinite(row[1]));
  if(!points.length)return <p className="ri-empty">此点云未保存坐标预览。</p>;
  const xs=points.map(p=>p[0]),ys=points.map(p=>p[1]),minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
  return <div className="ri-point-cloud"><svg role="img" aria-label="扩展点云预览" data-testid="point-cloud" viewBox="0 0 600 320" style={{width:'100%',maxHeight:360,padding:16}}>
    <path d="M 30 20 V 290 H 580" fill="none" stroke="var(--ri-muted)"/>
    {points.map((point,index)=><circle key={index} cx={40+(point[0]-minX)/Math.max(maxX-minX,1)*530} cy={280-(point[1]-minY)/Math.max(maxY-minY,1)*250} r={5} fill="var(--ri-accent)"><title>{point[0]}, {point[1]}</title></circle>)}
  </svg><p className="ri-fidelity">独立类型 {snapshot.descriptor.backend} · {snapshot.fidelity} · 显示 {points.length} 个已保存坐标；单位：{snapshot.descriptor.unit||'未标注'}</p></div>;
}
export function registerPointCloudRenderer(registry:RendererRegistry){
  registry.register({protocolVersion:1,id:'example.pointcloud',supports:descriptor=>descriptor.backend==='example.pointcloud'&&descriptor.capabilities.includes('preview'),Component:PointCloudView});
}
