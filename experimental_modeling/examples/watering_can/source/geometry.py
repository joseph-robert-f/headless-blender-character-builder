import math

def sweep(points, outer, inner=None, sides=16):
    vertices=[]; faces=[]; count=len(points)
    radii=[outer] if inner is None else [outer,inner]
    for radius in radii:
        for i,p in enumerate(points):
            a=points[max(i-1,0)]; b=points[min(i+1,count-1)]
            dx=b[0]-a[0]; dz=b[2]-a[2]; d=math.hypot(dx,dz)
            for k in range(sides):
                angle=2*math.pi*k/sides
                vertices.append([p[0]-dz/d*radius*math.cos(angle),p[1]+radius*math.sin(angle),p[2]+dx/d*radius*math.cos(angle)])
    for layer in range(len(radii)):
        offset=layer*count*sides
        for i in range(count-1):
            for k in range(sides):
                a=offset+i*sides+k; b=offset+i*sides+(k+1)%sides
                f=[a,b,b+sides,a+sides]
                faces.append(f if layer==0 else list(reversed(f)))
    if inner is None:
        faces.extend([list(reversed(range(sides))),list(range((count-1)*sides,count*sides))])
    else:
        for end in [0,count-1]:
            for k in range(sides):
                a=end*sides+k; b=end*sides+(k+1)%sides; offset=count*sides
                faces.append([a,a+offset,b+offset,b])
    return vertices,faces

def body():
    # Hollow open-top solid shell with floor, no face across the open mouth.
    n=64; profile=[(1,0),(1,1.6),(.86,1.6),(.86,.14)]
    vertices=[[r*math.cos(2*math.pi*k/n),r*math.sin(2*math.pi*k/n),z] for r,z in profile for k in range(n)]
    faces=[]
    for i in range(3):
        for k in range(n):
            a=i*n+k; b=i*n+(k+1)%n; faces.append([a,b,b+n,a+n])
    faces += [list(reversed(range(n))),list(range(3*n,4*n))]
    return vertices,faces

def handle(radius):
    points=[(-.94-.95*math.sin(math.pi*i/32),0,1.35-i/32+.12*math.sin(2*math.pi*i/32)) for i in range(33)]
    return sweep(points,radius)

def spout(lift):
    points=[]
    for i in range(25):
        t=i/24; s=max(0,(t-.125)/.875)
        points.append((.82+1.95*t,0,.55+1.1*max(0,(t-.125)/.875)**2+lift*s*s))
    return sweep(points,.21,.135)
