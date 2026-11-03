export type ComplexMode='real'|'imag'|'magnitude';
type Tagged={type?:string;value?:unknown;real?:unknown;imag?:unknown};
export function numericCell(value:unknown,mode:ComplexMode='real'):number|null{
  if(typeof value==='number')return value;
  if(typeof value==='boolean')return value?1:0;
  if(value && typeof value==='object'){
    const tag=value as Tagged;
    if(tag.type==='nonfinite')return tag.value==='nan'?NaN:tag.value==='inf'?Infinity:-Infinity;
    if(tag.type==='complex'){
      const real=numericCell(tag.real),imag=numericCell(tag.imag);
      return real===null||imag===null?null:mode==='real'?real:mode==='imag'?imag:Math.hypot(real,imag);
    }
  }
  return null;
}
export function displayCell(value:unknown):string{
  if(value===null || value===undefined)return '缺失';
  if(typeof value==='number')return Number.isInteger(value)?String(value):value.toPrecision(5);
  if(typeof value==='string' || typeof value==='boolean')return String(value);
  const tag=value as Tagged;
  if(tag.type==='nonfinite')return tag.value==='nan'?'NaN':tag.value==='inf'?'Inf':'−Inf';
  if(tag.type==='complex')return `${displayCell(tag.real)} + ${displayCell(tag.imag)}i`;
  if(['datetime','timedelta','truncated-string'].includes(tag.type||''))return String(tag.value);
  if(tag.type==='unavailable')return '不可用';
  return JSON.stringify(value);
}
export function planeAxes(shape:number[]){return {fixed:Array.from({length:Math.max(0,shape.length-2)},(_,i)=>i),plane:Array.from({length:Math.min(2,shape.length)},(_,i)=>Math.max(0,shape.length-2)+i)};}
export function cellColor(value:number|null,min:number,max:number):string{
  if(value===null)return '#5d6873';
  if(!Number.isFinite(value))return '#bb514c';
  if(min===max)return '#97a4ab';
  const extent=Math.max(Math.abs(min),Math.abs(max),Number.MIN_VALUE);
  const position=Math.max(0,Math.min(1,(value/extent-min/extent)/(max/extent-min/extent)));
  const colors=[[39,69,113],[52,150,153],[250,209,98]],index=position<.5?0:1,t=position<.5?position*2:(position-.5)*2;
  return `rgb(${colors[index].map((v,i)=>Math.round(v+(colors[index+1][i]-v)*t)).join(',')})`;
}
