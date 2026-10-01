# SPDX-License-Identifier: GPL-3.0-or-later
"""Independent pure mesh construction; no external data or side effects."""
import math

def tube(points, radii, sides=8):
    vertices=[]
    for i,p in enumerate(points):
        a=points[max(0,i-1)]; b=points[min(len(points)-1,i+1)]
        tangent=[b[j]-a[j] for j in range(3)]
        d=math.hypot(tangent[0],tangent[2]); u=[-tangent[2]/d,0,tangent[0]/d]
        length=math.sqrt(sum(t*t for t in tangent)); t=[v/length for v in tangent]
        w=[t[1]*u[2]-t[2]*u[1],t[2]*u[0]-t[0]*u[2],t[0]*u[1]-t[1]*u[0]]
        for k in range(sides):
            c=math.cos(k*2*math.pi/sides); s=math.sin(k*2*math.pi/sides)
            vertices.append([p[j]+radii[i]*(u[j]*c+w[j]*s) for j in range(3)])
    faces=[]
    for i in range(len(points)-1):
        for k in range(sides):
            a=i*sides+k; b=i*sides+(k+1)%sides
            faces.append([a,b,b+sides,a+sides])
    faces += [list(reversed(range(sides))),list(range((len(points)-1)*sides,len(points)*sides))]
    return vertices,faces

def crescent(height):
    vertices=[]; n=24
    for i in range(n+1):
        t=i/n; a=math.radians(-120+240*t)
        width=.20+.28*math.sin(math.pi*t); outer=.94; inner=outer-width
        section=[(outer,0),(outer,height),(outer-.08,height),(outer-.08,.08),
                 (inner+.08,.08),(inner+.08,height),(inner,height),(inner,0)]
        for r,z in section: vertices.append([2.3+r*math.cos(a),r*math.sin(a),z])
    faces=[]
    for i in range(n):
        for j in range(8):
            a=i*8+j; b=i*8+(j+1)%8; faces.append([a,a+8,b+8,b])
    faces += [list(range(7,-1,-1)),list(range(n*8,n*8+8))]
    return vertices,faces
