
with16=0

for i in range(1, 4092):
    g= open(str(i).zfill(4))
    d,n= [int(a) for a in g.readline()[:-1].split(" ")]

    thefacets=[]
    base1=set(range(14)); base2=set(range(15,28))
    vertices= set([])

    for l in g:
        thefacet= {int(a) for a in l[:-2].split(" ")}
        thefacets.append(thefacet)
        vertices= vertices | thefacet

    base1= base1& vertices
    base2= base2 & vertices

    if len(base1)==8 and len(base2)==8:
        with16+=1
        notneighbours1= {v:len([u for u in base1-{v} if len([f for f in thefacets if u in f and v in f])==0]) for v in base1}
        notneighbours2= {v:len([u for u in base2-{v} if len([f for f in thefacets if u in f and v in f])==0]) for v in base2}

        if all([notneighbours1[v]==1 for v in base1]) or all([notneighbours2[v]==1 for v in base2]):
            print(i)

    g.close()

print(with16)
