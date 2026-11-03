import json
import re


def safe_text(value,limit=16384):
    text=json.dumps(value,ensure_ascii=False,indent=2) if not isinstance(value,str) else value
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]','',text[:limit])


def variable_row(value):
    descriptor=value['descriptor']
    return (safe_text(value['name'],128),' × '.join(map(str,descriptor.get('shape') or [])) or 'scalar/metadata',
            safe_text(descriptor.get('dtype') or descriptor.get('kind') or '',128),str(value['version']),value['fidelity'])
