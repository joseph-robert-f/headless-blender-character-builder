"""Novel robot composition using ordinary Python construction and shared geometry."""
from geometry import add, box, tube, bezier, bent_leg, tray

LEG_ENDPOINTS={
    'leg_front_left': ((-.8,.85,1.15),(-1.6,1.3,.09)),
    'leg_front_right': ((.8,.85,1.15),(1.6,1.3,.09)),
    'leg_middle_left': ((-.8,0,1.15),(-1.75,0,.09)),
    'leg_middle_right': ((.8,0,1.15),(1.75,0,.09)),
    'leg_rear_left': ((-.8,-.85,1.15),(-1.6,-1.3,.09)),
    'leg_rear_right': ((.8,-.85,1.15),(1.6,-1.3,.09)),
}


def meshes(params):
    result={'body':box((-.8,-1.2,.95),(.8,1.2,1.45))}
    offset=params.get('mast_offset',[0,0,0])
    # Asymmetric curved sensor mast, intentionally unlike a primitive stack.
    controls=[(-.25,.45,1.45),(-.6,.7,2.25),(.55,.95,2.25),(.35,1.05,2.75)]
    result['mast']=tube([add(p,offset) for p in bezier(controls)],.10)
    result['cargo_tray']=tray(params.get('tray_width',1.4),params.get('tray_wall',.1))
    for name,(start,end) in LEG_ENDPOINTS.items():
        side=-1 if 'left' in name else 1
        factor=params.get('front_leg_factor',1.) if 'front' in name else 1.
        result[name]=tube(bent_leg(start,end,(side,0,0),factor),.075)
    if params.get('bad_body_shift'):
        v,f=result['body']; result['body']=([add(p,(params['bad_body_shift'],0,0)) for p in v],f)
    return result
