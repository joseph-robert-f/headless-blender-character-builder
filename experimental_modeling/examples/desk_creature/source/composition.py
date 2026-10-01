# SPDX-License-Identifier: GPL-3.0-or-later
import math
from mesh_shapes import tube, crescent

def grounded_leg(points, radii):
    vertices,faces=tube(points,radii)
    # Flatten only the endpoint cap onto the shared desk plane Z=0.
    for vertex in vertices[-8:]:
        vertex[2]=0.0
    return vertices,faces

def meshes(params):
    arch=params['tail_arch']; h=params['container_height']; tail=[]
    for i in range(17):
        t=i/16
        tail.append((-.5-1.15*math.sin(math.pi*t),.52+.7*t,1.0+1.5*t+arch*math.sin(math.pi*t)))
    return {
        'tail':tube(tail,[.16-.10*i/16 for i in range(17)]),
        'leg_left':grounded_leg([(-.52,-.20,.95),(-1.08,-.42,.61),(-1.22,-.66,.13)],[.17,.13,.17]),
        'leg_right':grounded_leg([(.50,-.25,.92),(.95,-.40,.33),(1.15,-.72,.13)],[.17,.13,.17]),
        'leg_rear':grounded_leg([(.10,.45,.95),(.40,1.0,.60),(.62,1.25,.13)],[.17,.13,.17]),
        'crescent':crescent(h),
    }
