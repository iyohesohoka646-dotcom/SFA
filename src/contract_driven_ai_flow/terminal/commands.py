"""A shell-free argument grammar that preserves Windows backslashes."""
import json


def words(text):
    result=[];value='';quote='';started=False
    for char in text:
        if quote:
            if char==quote:quote=''
            else:value+=char
            started=True
        elif char in ('"',"'"):quote=char;started=True
        elif char.isspace():
            if started:result.append(value);value='';started=False
        else:value+=char;started=True
    if quote:raise ValueError('Unclosed command quote')
    if started:result.append(value)
    return result


def parse_command(text):
    text=text.strip()
    if text.startswith('/model configure '):
        return 'models.configure',{'profile':json.loads(text[len('/model configure '):])}
    parts=words(text)
    if not parts or not parts[0].startswith('/'):raise ValueError('Use a slash command; /help lists the commands')
    name,args=parts[0][1:],parts[1:]
    if name in ('help','quit','runs'):return name,{}
    if name=='open':
        if not args:raise ValueError('/open requires a script path')
        values={'script':args[0]}
        if len(args)==3 and args[1]=='--python':values['interpreter']=args[2]
        elif len(args)!=1:raise ValueError('Use /open SCRIPT [--python PYTHON]')
        return name,values
    if name=='run':
        values={}
        if args and args[0]!='--':values['script']=args.pop(0)
        if args and args[0]=='--':args=args[1:]
        if args:values['arguments']=args
        return name,values
    if name in ('resume','continue','cancel'):
        return name,{'run_id':args[0]} if args else {}
    if name=='vars':return name,{'search':' '.join(args)}
    if name=='inspect' and len(args)==1:return name,{'snapshot_id':args[0]}
    if name=='explain':
        values={};command='explain'
        if args and not args[0].startswith('--'):values['operation_id']=args.pop(0)
        while args:
            option=args.pop(0)
            if option=='--sample':values['include_sample']=True
            elif option=='--context':command='explanation-context'
            elif option in ('--provider','--model') and args:values['provider_id' if option=='--provider' else 'model']=args.pop(0)
            else:raise ValueError('Invalid explanation option')
        return command,values
    if name=='model':
        if not args:return 'models.list',{}
        if args[0]=='search':return 'models.search',{'search':' '.join(args[1:])}
        if args[0]=='test' and len(args) in (2,3):return 'models.test',{'profile_id':args[1],'inference':len(args)==3 and args[2]=='--inference'}
        if len(args)==2:return 'models.use',{'profile_id':args[0],'model':args[1]}
    if name=='probe':
        if args==['list']:return 'probe.list',{}
        if len(args)>=3 and args[0]=='preview':return 'probe.preview',{'snapshot_id':args[1],'kind':args[2]}
        if len(args) in (2,3,4) and args[0]=='add':return 'probe.add',{'kind':args[1],'binding':args[2] if len(args)>2 else '*','policy':args[3] if len(args)>3 else 'continue'}
    raise ValueError('Unknown command or arguments; use /help')
