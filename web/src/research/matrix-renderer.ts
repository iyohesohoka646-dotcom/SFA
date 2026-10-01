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
  if(value===null)return '#687f8c';
  if(!Number.isFinite(value))return '#f3a392';
  const scale=Math.max(Math.abs(min),Math.abs(max),Number.MIN_VALUE),position=Math.min(1,Math.abs(value/scale));
  const base=value<0?[109,164,210]:[122,222,193],background=[23,43,57];
  return `rgb(${base.map((n,i)=>Math.round(background[i]+(n-background[i])*position)).join(',')})`;
}
