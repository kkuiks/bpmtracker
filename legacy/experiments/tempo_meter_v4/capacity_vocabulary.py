"""Keep nominal grouping separate from sparse and subdivided rhythm patterns."""
from functools import lru_cache
from .bar_structure import vocabulary as base_vocabulary


@lru_cache(None)
def vocabulary():
    grouped={}
    for state in base_vocabulary():grouped.setdefault((state['n'],state['d'],state['group']),[]).append(state)
    result=[]
    for states in grouped.values():
        result.extend(states)
        prototype=states[0]
        for rhythm in ['sparse_groups','duple_subdivision']:
            for visibility in ['observed','weak']:
                result.append(dict(prototype,rhythm=rhythm,visibility=visibility))
    return tuple(result)
