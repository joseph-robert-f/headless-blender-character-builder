"""Small generic geometry constructors; no Blender or recipe dispatcher required."""
from math import cos, sin, tau, sqrt


def add(a, b): return tuple(x+y for x,y in zip(a,b))
def sub(a, b): return tuple(x-y for x,y in zip(a,b))
def scale(a, s): return tuple(x*s for x in a)
def norm(a): return sqrt(sum(x*x for x in a))
def unit(a): return scale(a, 1/norm(a))
def cross(a,b): return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def box(low, high):
    x,y,z=low; X,Y,Z=high
    return ([(x,y,z),(X,y,z),(X,Y,z),(x,Y,z),(x,y,Z),(X,y,Z),(X,Y,Z),(x,Y,Z)],
            [(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)])


def merge(*meshes):
    vertices,faces=[],[]
    for v,f in meshes:
        offset=len(vertices); vertices.extend(v); faces.extend(tuple(i+offset for i in face) for face in f)
    return vertices,faces


def tube(points, radius, sides=12):
    """Polyline tube: contiguous rings then real, face-connected cap-center vertices."""
    vertices=[]; faces=[]
    for i,p in enumerate(points):
        tangent=unit(sub(points[min(i+1,len(points)-1)],points[max(0,i-1)]))
        axis=(0,0,1) if abs(tangent[2]) < .9 else (0,1,0)
        u=unit(cross(tangent,axis)); v=cross(tangent,u)
        vertices.extend(add(p,add(scale(u,radius*cos(tau*j/sides)),scale(v,radius*sin(tau*j/sides)))) for j in range(sides))
    for i in range(len(points)-1):
        for j in range(sides):
            a=i*sides+j; b=i*sides+(j+1)%sides
            faces.append((a,b,b+sides,a+sides))
    vertices.extend([points[0],points[-1]])
    start=len(vertices)-2; end=start+1; last=(len(points)-1)*sides
    for j in range(sides):
        faces.extend([(start,(j+1)%sides,j),(end,last+j,last+(j+1)%sides)])
    return vertices,faces


def bezier(control, samples=25):
    a,b,c,d=control
    return [tuple((1-t)**3*a[k]+3*(1-t)**2*t*b[k]+3*(1-t)*t*t*c[k]+t**3*d[k] for k in range(3)) for t in (i/(samples-1) for i in range(samples))]


def bent_leg(start, end, outward, length_factor):
    """Keep both endpoints, increase geometric centerline length by knee displacement."""
    if length_factor < 1: raise ValueError('length_factor must be at least one')
    midpoint=scale(add(start,end),.5)
    direction=unit(outward)
    def points(bend): return [start,add(midpoint,scale(direction,bend)),end]
    def length(bend):
        a,b,c=points(bend); return norm(sub(a,b))+norm(sub(b,c))
    base_bend=.32; target=length(base_bend)*length_factor
    low,high=base_bend,max(1.,target)
    for _ in range(64):
        mid=(low+high)/2
        if length(mid)<target: low=mid
        else: high=mid
    return points((low+high)/2)


def tray(width, wall, rear=-2.1, front=-.9, bottom=1.4, top=1.85):
    """Open-top concave shell. Index pairs expose actual wall and floor thickness."""
    if width<=2*wall or front-rear<=2*wall or top-bottom<=wall or wall<=0: raise ValueError('invalid tray dimensions')
    outer_bottom=[(-width/2,rear,bottom),(width/2,rear,bottom),(width/2,front,bottom),(-width/2,front,bottom)]
    outer_top=[(x,y,top) for x,y,_ in outer_bottom]
    inner_top=[(-width/2+wall,rear+wall,top),(width/2-wall,rear+wall,top),(width/2-wall,front-wall,top),(-width/2+wall,front-wall,top)]
    inner_floor=[(x,y,bottom+wall) for x,y,_ in inner_top]
    vertices=outer_bottom+outer_top+inner_top+inner_floor
    faces=[(3,2,1,0),(12,13,14,15)]
    for i in range(4):
        j=(i+1)%4
        faces.extend([(i,j,j+4,i+4),(i+4,j+4,j+8,i+8),(i+8,j+8,j+12,i+12)])
    # Two fixed mounting tabs, deliberately independent of overall tray width.
    mounts=[box((x-.06,-1.16,1.35),(x+.06,-1.04,1.42)) for x in (-.5,.5)]
    return merge((vertices,faces),*mounts)
