/** Arguments become argv strings; no shell interpolation is performed. */
export function parseArguments(text:string):string[]{
  if(text.trimStart().startsWith('[')){
    let parsed:unknown;try{parsed=JSON.parse(text);}catch{throw new Error('脚本参数 JSON 数组无效。');}
    if(!Array.isArray(parsed)||parsed.some(value=>typeof value!=='string'))throw new Error('脚本参数必须是字符串数组。');
    return parsed;
  }
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

/** JSON arrays round-trip arguments that contain both quote types. */
export function formatArguments(values:string[]):string{return values.length?JSON.stringify(values):'';}
