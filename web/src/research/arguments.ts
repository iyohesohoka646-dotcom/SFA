/** Arguments become argv strings; no shell interpolation is performed. */
export function parseArguments(text:string):string[]{
  const arguments_:string[]=[];let value='',quote='',started=false;
  for(const char of text){
    if(quote){if(char===quote)quote='';else value+=char;started=true;}
    else if(char==='"'||char==="'"){quote=char;started=true;}
    else if(/\s/.test(char)){if(started){arguments_.push(value);value='';started=false;}}
    else{value+=char;started=true;}
  }
  if(quote)throw new Error('脚本参数有未闭合的引号。');
  if(started)arguments_.push(value);return arguments_;
}
