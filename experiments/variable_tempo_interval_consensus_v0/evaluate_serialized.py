"""Evaluation-only output repair: retain undefined-distance reasons without altering predictions."""
import math
import sys
from . import evaluate
from .io import write


def sanitized_write(path,value):
    undefined=[]
    def clean(item,location=''):
        if isinstance(item,float) and not math.isfinite(item):
            undefined.append(dict(path=location,original_value=str(item),reason='Undefined/unbounded distance; reference-event availability and unmatched counts retained'))
            return None
        if isinstance(item,dict):return {key:clean(child,location+'/'+str(key)) for key,child in item.items()}
        if isinstance(item,list):return [clean(child,location+'/'+str(i)) for i,child in enumerate(item)]
        return item
    result=clean(value)
    if undefined:
        result['undefined_metric_values']=undefined
        result['evaluation_serialization_repair_only']=True
        print('UNDEFINED_METRICS_RETAINED',len(undefined),flush=True)
    write(path,result)


if __name__=='__main__':
    evaluate.write=sanitized_write
    evaluate.main()
